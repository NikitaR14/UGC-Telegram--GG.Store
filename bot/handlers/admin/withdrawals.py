from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.db import BotRepository, WithdrawalRequest, WithdrawalRequestStatus, get_session_factory
from bot.handlers.admin.moderation import is_valid_admin_callback, is_valid_admin_message
from bot.keyboards.admin_kb import (
    get_admin_dashboard_keyboard,
    get_admin_withdrawal_list_keyboard,
    get_admin_withdrawal_request_keyboard,
)
from bot.services.metrika import MetrikaGoal, track_metrika_goal
from bot.services.notification import send_notification
from bot.services.payment import build_withdrawal_request_text, format_amount

router = Router(name="admin.withdrawals")


class AdminWithdrawalState(StatesGroup):
    """Состояние ввода причины отказа по общей заявке."""

    waiting_for_reject_reason = State()


@router.callback_query(F.data.startswith("admin:withdrawals:"))
async def show_withdrawal_requests(callback: CallbackQuery) -> None:
    """Показывает список общих заявок в указанном статусе."""

    if not await is_valid_admin_callback(callback):
        return
    status, page = parse_list_callback(callback.data)
    await callback.answer()
    repository = BotRepository(get_session_factory())
    result = await repository.get_admin_withdrawal_requests_page(status, page)
    items = [(item.request_id, build_list_label(item)) for item in result.items]
    text = "💸 <b>Заявки на вывод</b>\n\n"
    text += "Выберите заявку." if items else "Нет заявок, ожидающих оплаты."
    await edit_callback(
        callback,
        text,
        get_admin_withdrawal_list_keyboard(
            status,
            result.page,
            result.total_pages,
            items,
        ),
    )


@router.callback_query(F.data.startswith("admin:withdrawal:view:"))
async def show_withdrawal_detail(callback: CallbackQuery) -> None:
    """Открывает подробную карточку общей заявки."""

    if not await is_valid_admin_callback(callback):
        return
    request_id = parse_request_id(callback.data, 3)
    if request_id is None:
        await callback.answer()
        return
    repository = BotRepository(get_session_factory())
    request = await repository.get_withdrawal_request(request_id)
    await callback.answer()
    if request is None:
        await edit_callback(callback, "Заявка не найдена.", get_admin_dashboard_keyboard())
        return
    back_status, back_page = parse_detail_context(callback.data)
    keyboard = get_admin_withdrawal_request_keyboard(
        request.request_id,
        back_status=back_status,
        back_page=back_page,
        include_actions=request.status == WithdrawalRequestStatus.PENDING.value,
    )
    await edit_callback(callback, build_withdrawal_request_text(request), keyboard)


@router.callback_query(F.data.startswith("admin:withdrawal:paid:"))
async def pay_withdrawal(callback: CallbackQuery) -> None:
    """Подтверждает оплату всех роликов в общей заявке."""

    if not await is_valid_admin_callback(callback):
        return
    request_id = parse_request_id(callback.data, 3)
    if request_id is None:
        await callback.answer()
        return
    repository = BotRepository(get_session_factory())
    try:
        await repository.pay_withdrawal_request(request_id)
    except ValueError:
        await callback.answer("Заявка уже обработана или недоступна.", show_alert=True)
        return
    request = await repository.get_withdrawal_request(request_id)
    await callback.answer("Выплата подтверждена.")
    if request is None:
        return
    await edit_callback(
        callback,
        build_withdrawal_request_text(request),
        get_admin_withdrawal_request_keyboard(
            request.request_id,
            back_status=WithdrawalRequestStatus.PAID.value,
            include_actions=False,
        ),
    )
    await notify_user_paid(callback.bot, request)
    if request.user is not None:
        await track_metrika_goal(
            request.user,
            MetrikaGoal.PAYOUT_SUM,
            extra_params={"payout_amount": request.total_amount},
        )


@router.callback_query(F.data.startswith("admin:withdrawal:reject:"))
async def request_reject_reason(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает причину отклонения общей заявки."""

    if not await is_valid_admin_callback(callback):
        return
    request_id = parse_request_id(callback.data, 3)
    if request_id is None:
        await callback.answer()
        return
    await state.set_state(AdminWithdrawalState.waiting_for_reject_reason)
    await state.update_data(
        request_id=request_id,
        chat_id=callback.message.chat.id if callback.message else None,
        message_id=callback.message.message_id if callback.message else None,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            f"Введите причину отклонения заявки #{request_id:05d}:",
        )


@router.callback_query(F.data == "admin:withdrawal:noop")
async def ignore_withdrawal_page_label(callback: CallbackQuery) -> None:
    """Отвечает на нажатие индикатора страницы."""

    await callback.answer()


@router.message(AdminWithdrawalState.waiting_for_reject_reason)
async def reject_withdrawal(message: Message, state: FSMContext) -> None:
    """Отклоняет общую заявку и освобождает ролики."""

    if not await is_valid_admin_message(message) or not message.text:
        return
    reason = message.text.strip()
    if not reason:
        await message.answer("Введите причину отклонения.")
        return
    data = await state.get_data()
    request_id = data.get("request_id")
    if not isinstance(request_id, int):
        await state.clear()
        return
    repository = BotRepository(get_session_factory())
    try:
        await repository.reject_withdrawal_request(request_id, reason)
    except ValueError:
        await state.clear()
        await message.answer("Заявка уже обработана.")
        return
    request = await repository.get_withdrawal_request(request_id)
    await state.clear()
    if request is None:
        return
    await edit_source_message(message.bot, data, request)
    await notify_user_rejected(message.bot, request)


async def notify_user_paid(bot: Bot, request: WithdrawalRequest) -> None:
    """Сообщает пользователю об оплате общей заявки."""

    text = (
        f"✅ <b>Заявка #{request.request_id:05d} оплачена.</b>\n\n"
        f"Отправлено <b>{format_amount(request.total_amount)} ₽</b> "
        f"на реквизиты <b>**** {request.details_tail}</b>."
    )
    await safe_notify_user(bot, request.user_id, text, request.request_id)


async def notify_user_rejected(bot: Bot, request: WithdrawalRequest) -> None:
    """Сообщает об отказе и возврате роликов в выбор."""

    text = (
        f"❌ <b>Заявка #{request.request_id:05d} отклонена.</b>\n\n"
        f"Причина: {escape(request.reject_reason or 'не указана')}.\n"
        "Ролики снова доступны для выбора."
    )
    await safe_notify_user(bot, request.user_id, text, request.request_id)


async def safe_notify_user(bot: Bot, user_id: int, text: str, request_id: int) -> None:
    """Безопасно отправляет уведомление по общей заявке."""

    try:
        await send_notification(bot, user_id, text)
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError) as error:
        logger.warning(
            "Withdrawal request user notification failed | request_id={} user={} error={}",
            request_id,
            user_id,
            str(error),
        )


async def edit_source_message(
    bot: Bot,
    data: dict[str, object],
    request: WithdrawalRequest,
) -> None:
    """Обновляет исходную карточку после отказа."""

    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=build_withdrawal_request_text(request),
        reply_markup=get_admin_withdrawal_request_keyboard(
            request.request_id,
            back_status=WithdrawalRequestStatus.REJECTED.value,
            include_actions=False,
        ),
        disable_web_page_preview=True,
    )


async def edit_callback(callback: CallbackQuery, text: str, keyboard: object) -> None:
    """Безопасно обновляет сообщение админа."""

    if callback.message is None:
        return
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise


def parse_list_callback(callback_data: str | None) -> tuple[str, int]:
    """Извлекает статус и страницу из callback."""

    parts = (callback_data or "").split(":")
    status = WithdrawalRequestStatus.PENDING.value
    if len(parts) > 2 and parts[2] in {item.value for item in WithdrawalRequestStatus}:
        status = parts[2]
    try:
        page = max(int(parts[3]), 1)
    except (IndexError, ValueError):
        page = 1
    return status, page


def parse_request_id(callback_data: str | None, index: int) -> int | None:
    """Извлекает request_id из callback."""

    try:
        return int((callback_data or "").split(":")[index])
    except (IndexError, ValueError):
        return None


def parse_detail_context(callback_data: str | None) -> tuple[str, int]:
    """Извлекает раздел и страницу из callback карточки."""

    parts = (callback_data or "").split(":")
    allowed_statuses = {item.value for item in WithdrawalRequestStatus}
    status = parts[4] if len(parts) > 4 and parts[4] in allowed_statuses else "pending"
    try:
        page = max(int(parts[5]), 1)
    except (IndexError, ValueError):
        page = 1
    return status, page


def build_list_label(request: WithdrawalRequest) -> str:
    """Формирует короткую подпись заявки в списке."""

    username = "без @"
    if request.user is not None and request.user.username:
        username = f"@{request.user.username}"
    return f"#{request.request_id:05d} | {username} | {format_amount(request.total_amount)} ₽"
