from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from loguru import logger

from bot.db import BotRepository, Video, WithdrawalRequest, get_session_factory
from bot.handlers.user.balance import render_balance
from bot.handlers.user.start import show_callback_screen
from bot.keyboards.admin_kb import get_admin_withdrawal_request_keyboard
from bot.keyboards.user_kb import (
    get_balance_keyboard,
    get_withdrawal_confirmation_keyboard,
    get_withdrawal_selection_keyboard,
)
from bot.services.notification import send_admin_notification
from bot.services.payment import build_withdrawal_request_text, format_amount
from bot.services.telegram_safe import safe_callback_answer
from bot.services.video import shorten_video_title

router = Router(name="user.withdrawal")


class WithdrawalState(StatesGroup):
    """Состояние выбора роликов для общей заявки."""

    selecting_videos = State()


@router.callback_query(F.data == "withdrawal:create")
async def start_withdrawal(callback: CallbackQuery, state: FSMContext) -> None:
    """Начинает выбор роликов для вывода."""

    repository = BotRepository(get_session_factory())
    user = await repository.get_user(callback.from_user.id)
    if user is None or not user.payment_method or not user.payment_details:
        await safe_callback_answer(
            callback,
            "Сначала привяжите реквизиты.",
            show_alert=True,
        )
        return
    await state.set_state(WithdrawalState.selecting_videos)
    await state.update_data(selected_video_ids=[])
    await safe_callback_answer(callback)
    await render_selection(callback, state, page=1)


@router.callback_query(F.data.startswith("withdrawal:page:"))
async def paginate_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключает страницу выбора роликов."""

    await safe_callback_answer(callback)
    await render_selection(callback, state, parse_page(callback.data))


@router.callback_query(F.data.startswith("withdrawal:toggle:"))
async def toggle_video(callback: CallbackQuery, state: FSMContext) -> None:
    """Добавляет или убирает ролик из выбора."""

    video_id, page = parse_toggle(callback.data)
    if video_id is None:
        await safe_callback_answer(callback)
        return
    data = await state.get_data()
    selected_ids = set(normalize_selected_ids(data.get("selected_video_ids")))
    if video_id in selected_ids:
        selected_ids.remove(video_id)
    else:
        selected_ids.add(video_id)
    await state.update_data(selected_video_ids=sorted(selected_ids))
    await safe_callback_answer(callback)
    await render_selection(callback, state, page)


@router.callback_query(F.data == "withdrawal:review")
async def review_withdrawal(callback: CallbackQuery, state: FSMContext) -> None:
    """Показывает итоговый состав общей заявки."""

    data = await state.get_data()
    selected_ids = normalize_selected_ids(data.get("selected_video_ids"))
    repository = BotRepository(get_session_factory())
    videos = await repository.get_user_videos_by_ids(callback.from_user.id, selected_ids)
    total_amount = round(sum(video.payout_amount for video in videos), 2)
    if not videos:
        await safe_callback_answer(callback, "Выберите хотя бы один ролик.", show_alert=True)
        return
    if total_amount < 300:
        await safe_callback_answer(callback, "Минимальная сумма вывода — 300 ₽.", show_alert=True)
        return
    await safe_callback_answer(callback)
    await show_callback_screen(
        callback,
        build_review_text(videos, total_amount),
        reply_markup=get_withdrawal_confirmation_keyboard(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "withdrawal:submit")
async def submit_withdrawal(callback: CallbackQuery, state: FSMContext) -> None:
    """Создаёт заявку после финальной транзакционной проверки."""

    data = await state.get_data()
    selected_ids = normalize_selected_ids(data.get("selected_video_ids"))
    repository = BotRepository(get_session_factory())
    try:
        created = await repository.create_withdrawal_request(
            callback.from_user.id,
            selected_ids,
        )
    except ValueError as error:
        await safe_callback_answer(callback, build_creation_error(str(error)), show_alert=True)
        return
    request = await repository.get_withdrawal_request(created.request_id)
    await state.clear()
    await safe_callback_answer(callback, "Заявка отправлена.")
    await show_callback_screen(
        callback,
        f"✅ <b>Заявка #{created.request_id:05d} создана.</b>\n\n"
        f"Сумма: <b>{format_amount(created.total_amount)} ₽</b>.\n"
        "Срок выплаты — до 3 рабочих дней.",
        reply_markup=get_balance_keyboard(),
    )
    if request is not None:
        await notify_admins(callback.bot, request)


@router.callback_query(F.data == "withdrawal:cancel")
async def cancel_withdrawal(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяет выбор и возвращает в баланс."""

    await state.clear()
    await safe_callback_answer(callback)
    await render_balance(callback)


@router.callback_query(F.data == "withdrawal:noop")
async def ignore_page_label(callback: CallbackQuery) -> None:
    """Отвечает на нажатие индикатора страницы."""

    await safe_callback_answer(callback)


async def render_selection(callback: CallbackQuery, state: FSMContext, page: int) -> None:
    """Обновляет экран выбора роликов."""

    repository = BotRepository(get_session_factory())
    result = await repository.get_user_eligible_videos_page(callback.from_user.id, page)
    data = await state.get_data()
    selected_ids = set(normalize_selected_ids(data.get("selected_video_ids")))
    if not result.items:
        await show_callback_screen(
            callback,
            "💸 <b>Создать заявку на вывод</b>\n\n"
            "Нет одобренных роликов, доступных для вывода.",
            reply_markup=get_balance_keyboard(),
        )
        return
    items = [build_selection_item(video, selected_ids) for video in result.items]
    await show_callback_screen(
        callback,
        "💸 <b>Создать заявку на вывод</b>\n\n"
        "Выберите один или несколько роликов. Минимум — 300 ₽.",
        reply_markup=get_withdrawal_selection_keyboard(items, result.page, result.total_pages),
    )


async def notify_admins(bot: Bot, request: WithdrawalRequest) -> None:
    """Отправляет новую общую заявку активным админам."""

    repository = BotRepository(get_session_factory())
    for admin_id in await repository.get_active_admin_ids():
        try:
            await send_admin_notification(
                bot,
                admin_id,
                build_withdrawal_request_text(request),
                get_admin_withdrawal_request_keyboard(request.request_id),
            )
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError) as error:
            logger.warning(
                "Withdrawal request notification failed | request_id={} admin={} error={}",
                request.request_id,
                admin_id,
                str(error),
            )


def build_selection_item(video: Video, selected_ids: set[int]) -> tuple[int, str, bool]:
    """Собирает подпись одного ролика в клавиатуре."""

    title = shorten_video_title(video.title or video.url, limit=24)
    label = f"{title} — {format_amount(video.payout_amount)} ₽"
    return video.video_id, label, video.video_id in selected_ids


def build_review_text(videos: list[Video], total_amount: float) -> str:
    """Формирует экран проверки выбранных роликов."""

    lines = ["💸 <b>Проверьте заявку</b>", ""]
    for video in videos[:25]:
        title = shorten_video_title(video.title or video.url)
        lines.append(
            f"• <a href=\"{video.url}\">{title}</a> — {format_amount(video.payout_amount)} ₽",
        )
    if len(videos) > 25:
        lines.append(f"… и ещё {len(videos) - 25}")
    lines.extend(["", f"<b>Итого: {format_amount(total_amount)} ₽</b>"])
    return "\n".join(lines)


def normalize_selected_ids(value: object) -> list[int]:
    """Очищает список выбранных video_id из FSM."""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int)]


def parse_page(callback_data: str | None) -> int:
    """Извлекает номер страницы из callback."""

    try:
        return max(int((callback_data or "").split(":")[2]), 1)
    except (IndexError, ValueError):
        return 1


def parse_toggle(callback_data: str | None) -> tuple[int | None, int]:
    """Извлекает video_id и страницу из callback."""

    parts = (callback_data or "").split(":")
    if len(parts) != 4:
        return None, 1
    try:
        return int(parts[2]), max(int(parts[3]), 1)
    except ValueError:
        return None, 1


def build_creation_error(error_text: str) -> str:
    """Преобразует ошибку создания в понятный текст."""

    if "payment details" in error_text:
        return "Сначала привяжите реквизиты."
    if "below minimum" in error_text:
        return "Минимальная сумма вывода — 300 ₽."
    if "not available" in error_text:
        return "Состав роликов изменился. Выберите их заново."
    return "Не удалось создать заявку."
