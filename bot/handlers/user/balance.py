from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.db import BotRepository, PaymentMethod, VideoStatus, Withdrawal, get_session_factory
from bot.handlers.user.start import WELCOME_TEXT
from bot.keyboards.user_kb import (
    get_balance_keyboard,
    get_main_menu_keyboard,
    get_payment_methods_keyboard,
    get_withdrawals_keyboard,
)
from bot.services.notification import notify_admins_about_payment_details
from bot.ui.emojis import BALANCE_TEXT, CARD_TEXT, PAYMENTS_TEXT, STAR_TEXT, SUCCESS_TEXT, USDT_TEXT

router = Router(name="user.balance")

BALANCE_TITLE = f"{BALANCE_TEXT} <b>Баланс</b>"
METHOD_LABELS = {
    PaymentMethod.CARD.value: f"{CARD_TEXT} Банковская карта",
    PaymentMethod.USDT.value: f"{USDT_TEXT} USDT TRC-20",
    PaymentMethod.GGSTORE.value: f"{STAR_TEXT} Баланс gg.store",
}


class BalanceState(StatesGroup):
    """Состояния сценария управления балансом."""

    waiting_for_payment_details = State()


@router.callback_query(F.data == "menu:balance")
async def show_balance(callback: CallbackQuery, state: FSMContext) -> None:
    """Показывает экран баланса пользователя."""

    await state.clear()
    await callback.answer()
    await render_balance(callback)


@router.callback_query(F.data == "balance:change_method")
async def choose_payment_method(callback: CallbackQuery) -> None:
    """Открывает экран выбора способа вывода."""

    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            "Выберите способ вывода:",
            reply_markup=get_payment_methods_keyboard(),
        )


@router.callback_query(F.data.startswith("balance:method:"))
async def request_payment_details(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохраняет выбранный способ и просит ввести реквизиты."""

    method = parse_method(callback.data)
    if method is None:
        await callback.answer()
        return

    await state.update_data(payment_method=method)
    await state.set_state(BalanceState.waiting_for_payment_details)
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            "Введите данные счёта:",
            reply_markup=get_payment_methods_keyboard(back_only=True),
        )


@router.message(BalanceState.waiting_for_payment_details)
async def save_payment_details(message: Message, state: FSMContext) -> None:
    """Сохраняет реквизиты пользователя и возвращает в экран баланса."""

    if message.from_user is None or not message.text:
        return

    data = await state.get_data()
    payment_method = data.get("payment_method")
    if not isinstance(payment_method, str):
        await state.clear()
        await message.answer(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )
        return

    repository = BotRepository(get_session_factory())
    existing_user = await repository.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    had_payment_details_before = bool(
        existing_user.payment_method and existing_user.payment_details,
    )
    user = await repository.save_payment_details(
        user_id=message.from_user.id,
        payment_method=payment_method,
        payment_details=message.text.strip(),
    )
    approved_count = await repository.count_user_videos_by_status(
        user_id=message.from_user.id,
        status=VideoStatus.APPROVED.value,
    )
    approved_video_ids = await repository.get_user_video_ids_by_status(
        user_id=message.from_user.id,
        status=VideoStatus.APPROVED.value,
    )
    await state.clear()
    await message.answer(f"{SUCCESS_TEXT} Счёт успешно сохранён!")
    await message.answer(
        await build_balance_text(message.from_user.id),
        reply_markup=get_balance_keyboard(),
    )
    if approved_count > 0 and not had_payment_details_before:
        await notify_admins_about_payment_details(
            bot=message.bot,
            user=user,
            approved_video_ids=approved_video_ids,
        )


@router.callback_query(F.data == "balance:history")
async def show_withdrawals_history(callback: CallbackQuery) -> None:
    """Показывает первую страницу истории выплат."""

    await callback.answer()
    await render_withdrawals_page(callback, page=1)


@router.callback_query(F.data.startswith("withdrawals:page:"))
async def paginate_withdrawals(callback: CallbackQuery) -> None:
    """Переключает страницы истории выплат."""

    await callback.answer()
    page = parse_page_number(callback.data)
    await render_withdrawals_page(callback, page=page)


@router.callback_query(F.data == "withdrawals:noop")
async def ignore_withdrawals_page_label(callback: CallbackQuery) -> None:
    """Подтверждает нажатие на индикатор страницы выплат."""

    await callback.answer()


@router.callback_query(F.data.in_({"balance:back", "withdrawals:back", "balance:return"}))
async def return_from_balance_screens(callback: CallbackQuery, state: FSMContext) -> None:
    """Возвращает пользователя из экрана баланса или истории выплат."""

    await state.clear()
    await callback.answer()
    if callback.data in {"withdrawals:back", "balance:return"}:
        await render_balance(callback)
        return

    if callback.message is not None:
        await callback.message.edit_text(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )


async def render_balance(callback: CallbackQuery) -> None:
    """Рендерит экран баланса."""

    if callback.from_user is None or callback.message is None:
        return

    await callback.message.edit_text(
        await build_balance_text(callback.from_user.id),
        reply_markup=get_balance_keyboard(),
    )


async def build_balance_text(user_id: int) -> str:
    """Формирует текст экрана баланса."""

    repository = BotRepository(get_session_factory())
    user = await repository.get_user(user_id)
    if user is None:
        return (
            f"{BALANCE_TITLE}\n\n"
            "Текущий баланс: <b>0 ₽</b>\n"
            "Всего выведено: <b>0 ₽</b>\n"
            "Реквизиты: <b>не привязаны</b>"
        )

    details_tail = build_details_tail(user.payment_details)
    return (
        f"{BALANCE_TITLE}\n\n"
        f"Текущий баланс: <b>{format_amount(user.balance)} ₽</b>\n"
        f"Всего выведено: <b>{format_amount(user.total_withdrawn)} ₽</b>\n"
        f"Реквизиты: <b>{details_tail}</b>"
    )


async def render_withdrawals_page(callback: CallbackQuery, page: int) -> None:
    """Рендерит страницу истории выплат."""

    if callback.from_user is None or callback.message is None:
        return

    repository = BotRepository(get_session_factory())
    result = await repository.get_user_withdrawals_page(
        user_id=callback.from_user.id,
        page=page,
    )
    text = build_withdrawals_text(result.items)
    await safe_edit_text(
        callback=callback,
        text=text,
        reply_markup=get_withdrawals_keyboard(
            page=result.page,
            total_pages=result.total_pages,
            has_items=bool(result.items),
        ),
    )


def build_withdrawals_text(withdrawals: list[Withdrawal]) -> str:
    """Формирует текст истории выплат."""

    header = f"{PAYMENTS_TEXT} <b>История выплат</b>\n\n"
    footer = (
        "\n\n"
        "<blockquote>Минимальная сумма вывода — 300 ₽\n"
        "Срок выплаты — 3 рабочих дня</blockquote>"
    )
    if not withdrawals:
        return (
            header
            + "Пока выплат нет.\n\n"
            + "<blockquote>Минимальная сумма вывода — 300 ₽\n"
            + "Срок выплаты — 3 рабочих дня</blockquote>"
        )

    cards = [format_withdrawal_card(withdrawal) for withdrawal in withdrawals]
    return header + "\n\n".join(cards) + footer


def format_withdrawal_card(withdrawal: Withdrawal) -> str:
    """Формирует карточку одной выплаты."""

    method = METHOD_LABELS.get(withdrawal.method, withdrawal.method or "Не указан")
    if withdrawal.details_tail and withdrawal.details_tail != "----":
        method = f"{method} **** {withdrawal.details_tail}"
    return (
        f"<b>Дата:</b> {format_date(withdrawal.paid_at)}\n"
        f"<b>Сумма:</b> {format_amount(withdrawal.amount)} ₽\n"
        f"<b>Способ вывода:</b> {method}"
    )


def build_details_tail(payment_details: str | None) -> str:
    """Возвращает маску реквизитов для экрана баланса."""

    if not payment_details:
        return "не привязаны"
    return f"**** {payment_details[-4:]}"


def format_amount(value: float) -> str:
    """Форматирует сумму без лишних нулей."""

    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_method(callback_data: str | None) -> str | None:
    """Извлекает способ вывода из callback data."""

    if not callback_data:
        return None
    parts = callback_data.split(":")
    if len(parts) != 3:
        return None
    method = parts[2]
    if method not in METHOD_LABELS:
        return None
    return method


def parse_page_number(callback_data: str | None) -> int:
    """Безопасно извлекает номер страницы выплат."""

    if not callback_data:
        return 1
    parts = callback_data.split(":")
    if len(parts) != 3:
        return 1
    try:
        return max(int(parts[2]), 1)
    except ValueError:
        return 1


def format_date(value: datetime) -> str:
    """Форматирует дату для истории выплат."""

    return value.strftime("%d.%m.%Y")


async def safe_edit_text(
    callback: CallbackQuery,
    text: str,
    reply_markup: object,
) -> None:
    """Безопасно редактирует сообщение, игнорируя одинаковое содержимое."""

    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return
        raise
