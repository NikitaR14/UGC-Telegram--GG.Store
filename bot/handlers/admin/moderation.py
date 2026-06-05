from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.config import get_settings
from bot.db import BotRepository, User, Video, VideoStatus, get_session_factory
from bot.keyboards.admin_kb import (
    get_admin_all_videos_list_keyboard,
    get_admin_dashboard_keyboard,
    get_admin_detail_keyboard,
    get_admin_list_keyboard,
    get_admin_paid_keyboard,
    get_admin_video_keyboard,
    get_admin_waiting_details_keyboard,
)
from bot.services.notification import (
    format_payment_method,
    notify_video_approved,
    send_admin_notification,
    notify_video_paid,
    notify_video_rejected,
)
from bot.services.metrika import MetrikaGoal, track_metrika_goal
from bot.services.video import shorten_video_title
from bot.ui.emojis import ERROR_TEXT, INBOX_TEXT, LIST_TEXT, PAYMENTS_TEXT, PIN_TEXT, SUCCESS_TEXT, SUPPORT_TEXT

router = Router(name="admin.moderation")

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
}
STATUS_LABELS = {
    VideoStatus.PENDING.value: "На рассмотрении",
    VideoStatus.APPROVED.value: "Одобрено",
    VideoStatus.REJECTED.value: "Отклонено",
    VideoStatus.PAID.value: "Оплачено",
}
SECTION_TITLES = {
    VideoStatus.PENDING.value: f"{INBOX_TEXT} <b>Новые заявки</b>",
    VideoStatus.APPROVED.value: f"{SUCCESS_TEXT} <b>Одобренные заявки</b>",
    VideoStatus.PAID.value: f"{PAYMENTS_TEXT} <b>Оплаченные заявки</b>",
    VideoStatus.REJECTED.value: f"{ERROR_TEXT} <b>Отклонённые заявки</b>",
    "all": f"{LIST_TEXT} <b>Все видео</b>",
}
PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
REJECTED_STATUS = "rejected"
PAID_STATUS = "paid"
APPROVE_PROMPT_TEXT = "Введите сумму выплаты для заявки #{video_id:05d}:"
REJECT_PROMPT_TEXT = "Введите причину отклонения заявки #{video_id:05d}:"
APPROVE_SUCCESS_TEXT = (
    f"{SUCCESS_TEXT} <b>Заявка #{{video_id:05d}} успешно принята.</b>\n\n"
    "<b>Пользователь:</b> {username_label}\n"
    "<b>Сумма выплаты:</b> {payout_amount} ₽\n"
    "<b>Способ вывода:</b> {payment_method}\n"
    "<b>Реквизиты:</b> <code>{payment_details}</code>\n\n"
    "Пользователь ждёт начисления средств."
)
APPROVE_WAITING_DETAILS_TEXT = (
    f"{SUCCESS_TEXT} <b>Заявка #{{video_id:05d}} успешно принята.</b>\n\n"
    "<b>Пользователь:</b> {username_label}\n"
    "<b>Сумма выплаты:</b> {payout_amount} ₽\n"
    "<b>Способ вывода:</b> {payment_method}\n"
    "<b>Реквизиты:</b> <code>{payment_details}</code>\n\n"
    "Ожидаем добавление реквизитов. После этого придёт отдельное уведомление."
)
APPROVE_WAITING_DETAILS_NOTICE_TEXT = (
    f"{PIN_TEXT} <b>Ожидаем добавление реквизитов</b>\n\n"
    "По заявке #{video_id:05d} у пользователя {username_label} пока не указаны реквизиты.\n"
    "После добавления реквизитов администраторам придёт уведомление."
)
REJECT_SUCCESS_TEXT = (
    f"{ERROR_TEXT} <b>Заявка #{{video_id:05d}} успешно отклонена.</b>\n\n"
    "<b>Причина отказа:</b>\n"
    "<blockquote>{reason}</blockquote>"
)
PAID_SUCCESS_TEXT = f"{SUCCESS_TEXT} Заявка #{{video_id:05d}} оплачена."
ADMIN_SESSION_REQUIRED_TEXT = "Сначала войдите в панель через /admin."
ADMIN_DASHBOARD_TEXT = (
    f"{SUPPORT_TEXT} <b>Панель администратора</b>\n\n"
    "Выберите раздел для работы с заявками."
)
ADMIN_TITLE_LENGTH = 28
PAYMENT_DETAILS_EMPTY_TEXT = "не привязаны"


class ModerationState(StatesGroup):
    """Состояния действий модератора."""

    waiting_for_payout_amount = State()
    waiting_for_reject_reason = State()


@router.callback_query(F.data == "admin:dashboard")
async def show_admin_dashboard(callback: CallbackQuery) -> None:
    """Показывает главное меню админ-панели."""

    if not await is_valid_admin_callback(callback):
        return

    await callback.answer()
    await safe_edit_admin_text(
        callback,
        ADMIN_DASHBOARD_TEXT,
        get_admin_dashboard_keyboard(),
    )


@router.callback_query(F.data.startswith("admin:menu:"))
async def show_admin_status_list(callback: CallbackQuery) -> None:
    """Открывает список заявок по выбранному статусу."""

    if not await is_valid_admin_callback(callback):
        return

    status = parse_status_from_menu(callback.data)
    if status is None:
        await callback.answer()
        return

    await callback.answer()
    if status == "all":
        await render_admin_all_videos_page(callback, page=1)
        return
    await render_admin_list_page(callback, status=status, page=1)


@router.callback_query(F.data.startswith("admin:all_videos:"))
async def paginate_admin_all_videos(callback: CallbackQuery) -> None:
    """Переключает страницы общего списка видео пользователей."""

    if not await is_valid_admin_callback(callback):
        return
    if callback.data == "admin:all_videos:noop":
        await callback.answer()
        return

    await callback.answer()
    await render_admin_all_videos_page(
        callback,
        page=parse_all_videos_page(callback.data),
    )


@router.callback_query(F.data.startswith("admin:list:"))
async def paginate_admin_status_list(callback: CallbackQuery) -> None:
    """Переключает страницы списка заявок в админке."""

    if not await is_valid_admin_callback(callback):
        return
    if callback.data == "admin:list:noop":
        await callback.answer()
        return

    status, page = parse_admin_list_callback(callback.data)
    if status is None:
        await callback.answer()
        return

    await callback.answer()
    await render_admin_list_page(callback, status=status, page=page)


@router.callback_query(F.data.startswith("admin:view:"))
async def show_admin_video_detail(callback: CallbackQuery) -> None:
    """Открывает детальную карточку заявки в админ-панели."""

    if not await is_valid_admin_callback(callback):
        return

    status, page, video_id = parse_admin_view_callback(callback.data)
    if status is None or video_id is None:
        await callback.answer()
        return

    await callback.answer()
    await render_admin_detail_page(
        callback=callback,
        list_status=status,
        list_page=page,
        video_id=video_id,
    )


@router.callback_query(F.data.startswith("admin:approve:"))
async def request_approve_amount(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает у администратора сумму выплаты."""

    if not await is_valid_admin_callback(callback):
        return

    video_id = parse_video_id(callback.data)
    if video_id is None:
        await callback.answer()
        return
    if not await is_video_in_status(video_id, PENDING_STATUS):
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    list_status, list_page = parse_action_context(callback.data)
    await state.set_state(ModerationState.waiting_for_payout_amount)
    await state.update_data(
        video_id=video_id,
        source_chat_id=get_chat_id(callback),
        source_message_id=get_message_id(callback),
        source_origin="panel" if list_status is not None else "notification",
        list_status=list_status,
        list_page=list_page,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(APPROVE_PROMPT_TEXT.format(video_id=video_id))


@router.message(ModerationState.waiting_for_payout_amount)
async def handle_approve_amount(message: Message, state: FSMContext) -> None:
    """Принимает сумму, одобряет заявку и начисляет баланс."""

    if not await is_valid_admin_message(message):
        return
    if not message.text:
        return

    payout_amount = parse_payout_amount(message.text)
    if payout_amount is None:
        await message.answer("Введите корректную сумму, например: 250 или 1250.50")
        return

    data = await state.get_data()
    video_id = data.get("video_id")
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    source_origin = data.get("source_origin")
    if not isinstance(video_id, int):
        await state.clear()
        return

    repository = BotRepository(get_session_factory())
    try:
        video = await repository.approve_video(video_id, payout_amount)
    except ValueError as error:
        await state.clear()
        await message.answer(get_moderation_error_text(str(error)))
        return

    user = await repository.get_user(video.user_id)
    if user is None:
        await state.clear()
        await message.answer("Пользователь заявки не найден.")
        return

    list_status = data.get("list_status")
    list_page = data.get("list_page")
    await state.clear()
    if source_origin == "panel":
        await render_admin_detail_message(
            bot=message.bot,
            video_id=video.video_id,
            back_status=list_status,
            back_page=list_page,
            chat_id=source_chat_id,
            message_id=source_message_id,
        )
    else:
        await update_admin_message_after_approve(
            bot=message.bot,
            video=video,
            user=user,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
    if not has_payment_details(user):
        await send_waiting_details_notice(
            bot=message.bot,
            video=video,
            user=user,
            chat_id=message.chat.id,
            back_status=list_status,
            back_page=list_page,
        )
    await notify_video_approved(message.bot, user, video)


@router.callback_query(F.data.startswith("admin:reject:"))
async def request_reject_reason(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает у администратора причину отклонения."""

    if not await is_valid_admin_callback(callback):
        return

    video_id = parse_video_id(callback.data)
    if video_id is None:
        await callback.answer()
        return
    if not await is_video_in_status(video_id, PENDING_STATUS):
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return

    list_status, list_page = parse_action_context(callback.data)
    await state.set_state(ModerationState.waiting_for_reject_reason)
    await state.update_data(
        video_id=video_id,
        source_chat_id=get_chat_id(callback),
        source_message_id=get_message_id(callback),
        source_origin="panel" if list_status is not None else "notification",
        list_status=list_status,
        list_page=list_page,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(REJECT_PROMPT_TEXT.format(video_id=video_id))


@router.message(ModerationState.waiting_for_reject_reason)
async def handle_reject_reason(message: Message, state: FSMContext) -> None:
    """Сохраняет причину и отклоняет заявку."""

    if not await is_valid_admin_message(message):
        return
    if not message.text:
        return

    reason = message.text.strip()
    if not reason:
        await message.answer("Введите причину отклонения заявки.")
        return
    data = await state.get_data()
    video_id = data.get("video_id")
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    source_origin = data.get("source_origin")
    if not isinstance(video_id, int):
        await state.clear()
        return

    repository = BotRepository(get_session_factory())
    try:
        video = await repository.reject_video(video_id, reason)
    except ValueError as error:
        await state.clear()
        await message.answer(get_moderation_error_text(str(error)))
        return

    user = await repository.get_user(video.user_id)
    if user is None:
        await state.clear()
        await message.answer("Пользователь заявки не найден.")
        return

    await state.clear()
    if source_origin == "panel":
        await render_admin_detail_message(
            bot=message.bot,
            video_id=video.video_id,
            back_status=data.get("list_status"),
            back_page=data.get("list_page"),
            chat_id=source_chat_id,
            message_id=source_message_id,
        )
    else:
        await update_admin_message_after_reject(
            bot=message.bot,
            video=video,
            reason=reason,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
    await notify_video_rejected(message.bot, user, video)


@router.callback_query(F.data.startswith("admin:paid:"))
async def mark_paid(callback: CallbackQuery) -> None:
    """Подтверждает выплату по одобренной заявке."""

    if not await is_valid_admin_callback(callback):
        return

    video_id = parse_video_id(callback.data)
    if video_id is None:
        await callback.answer()
        return
    if not await is_video_in_status(video_id, APPROVED_STATUS):
        await callback.answer("Заявка недоступна для выплаты.", show_alert=True)
        return

    repository = BotRepository(get_session_factory())
    video = await repository.get_video(video_id)
    if video is None:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return

    try:
        await repository.mark_video_paid(video_id)
    except ValueError as error:
        await callback.answer(get_paid_error_text(str(error)), show_alert=True)
        return

    user = await repository.get_user(video.user_id)
    updated_video = await repository.get_video(video_id)
    if user is not None and updated_video is not None:
        await track_metrika_goal(
            user,
            MetrikaGoal.PAYOUT_SUM,
            extra_params={
                "video_id": updated_video.video_id,
                "payout_amount": float(updated_video.payout_amount or 0),
            },
        )
        await notify_video_paid(callback.bot, user, updated_video)

    await callback.answer("Выплата подтверждена.")
    if callback.message is not None:
        list_status, list_page = parse_action_context(callback.data)
        if list_status is not None:
            await render_admin_detail_message(
                bot=callback.bot,
                video_id=video_id,
                back_status=list_status,
                back_page=list_page,
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
            )
        else:
            await callback.message.edit_text(PAID_SUCCESS_TEXT.format(video_id=video_id))


async def notify_admins_about_video(
    bot: Bot,
    video: Video,
    username: str | None,
) -> None:
    """Отправляет новую заявку всем администраторам проекта."""

    repository = BotRepository(get_session_factory())
    admin_ids = await repository.get_active_admin_ids()
    text = build_admin_video_text(video, username)
    keyboard = get_admin_video_keyboard(video.video_id)
    for admin_id in admin_ids:
        try:
            await send_admin_notification(
                bot=bot,
                chat_id=admin_id,
                text=text,
                reply_markup=keyboard,
            )
        except TelegramForbiddenError as error:
            logger.warning(
                "Admin notification forbidden | admin={} video_id={} error={}",
                admin_id,
                video.video_id,
                str(error),
            )
        except TelegramBadRequest as error:
            logger.warning(
                "Admin notification bad request | admin={} video_id={} error={}",
                admin_id,
                video.video_id,
                str(error),
            )
        except TelegramNetworkError as error:
            logger.warning(
                "Admin notification network error | admin={} video_id={} error={}",
                admin_id,
                video.video_id,
                str(error),
            )


async def update_admin_message_after_approve(
    bot: Bot,
    video: Video,
    user: User,
    source_chat_id: object,
    source_message_id: object,
) -> None:
    """Обновляет админское сообщение после одобрения заявки."""

    username_label = f"@{user.username}" if user.username else "без username"
    if not isinstance(source_chat_id, int) or not isinstance(source_message_id, int):
        return
    has_details = has_payment_details(user)
    await bot.edit_message_text(
        chat_id=source_chat_id,
        message_id=source_message_id,
        text=build_approve_success_text(video, user, username_label, has_details),
        reply_markup=get_admin_paid_keyboard(video.video_id) if has_details else None,
    )


def build_approve_success_text(
    video: Video,
    user: User,
    username_label: str,
    has_details: bool,
) -> str:
    """Формирует админский текст после одобрения заявки."""

    template = APPROVE_SUCCESS_TEXT if has_details else APPROVE_WAITING_DETAILS_TEXT
    payment_method = format_payment_method(user.payment_method)
    payment_details = escape(build_admin_payment_details(user))
    return template.format(
        video_id=video.video_id,
        username_label=username_label,
        payout_amount=int(video.payout_amount),
        payment_method=payment_method,
        payment_details=payment_details,
    )


async def send_waiting_details_notice(
    bot: Bot,
    video: Video,
    user: User,
    chat_id: int,
    back_status: object,
    back_page: object,
) -> None:
    """Отправляет отдельное сообщение администратору об ожидании реквизитов."""

    username_label = f"@{user.username}" if user.username else "без username"
    normalized_back_status = normalize_status(back_status) or APPROVED_STATUS
    safe_back_page = normalize_page(back_page)
    await bot.send_message(
        chat_id=chat_id,
        text=APPROVE_WAITING_DETAILS_NOTICE_TEXT.format(
            video_id=video.video_id,
            username_label=username_label,
        ),
        reply_markup=get_admin_waiting_details_keyboard(
            video_id=video.video_id,
            back_status=normalized_back_status,
            back_page=safe_back_page,
        ),
    )


async def update_admin_message_after_reject(
    bot: Bot,
    video: Video,
    reason: str,
    source_chat_id: object,
    source_message_id: object,
) -> None:
    """Отправляет сообщение об отклонении заявки администратору."""

    if not isinstance(source_chat_id, int) or not isinstance(source_message_id, int):
        return
    await bot.edit_message_text(
        chat_id=source_chat_id,
        message_id=source_message_id,
        text=REJECT_SUCCESS_TEXT.format(video_id=video.video_id, reason=reason),
    )


def build_admin_video_text(video: Video, username: str | None) -> str:
    """Формирует текст новой заявки для администратора."""

    username_label = f"@{username}" if username else "без username"
    platform = PLATFORM_LABELS.get(video.platform, video.platform)
    created_at = format_datetime(video.created_at)
    title = shorten_video_title(video.title or video.url)
    return (
        f"<b>Номер заявки:</b> {video.video_id:05d}\n"
        f"<b>Название:</b> <a href=\"{video.url}\">{title}</a>\n"
        f"<b>Пользователь:</b> {username_label}\n"
        f"<b>Платформа:</b> {platform}\n"
        f"<b>Дата добавления:</b> {created_at}\n"
        f"<b>Сумма выплаты:</b> {int(video.payout_amount)} ₽"
    )


async def render_admin_list_page(
    callback: CallbackQuery,
    status: str,
    page: int,
) -> None:
    """Рендерит список заявок выбранного раздела админки."""

    repository = BotRepository(get_session_factory())
    result = await repository.get_admin_videos_page(status=status, page=page)
    text = build_admin_list_text(status, result.items)
    keyboard_items = build_admin_list_items(result.items)
    await safe_edit_admin_text(
        callback,
        text,
        get_admin_list_keyboard(
            status=status,
            page=result.page,
            total_pages=result.total_pages,
            items=keyboard_items,
        ),
    )


async def render_admin_all_videos_page(
    callback: CallbackQuery,
    page: int,
) -> None:
    """Рендерит отдельный раздел со всеми видео пользователей."""

    repository = BotRepository(get_session_factory())
    result = await repository.get_all_videos_page(page=page)
    text = build_admin_all_videos_text(result.items)
    await safe_edit_admin_text(
        callback,
        text,
        get_admin_all_videos_list_keyboard(
            page=result.page,
            total_pages=result.total_pages,
            has_items=bool(result.items),
        ),
    )


async def render_admin_detail_page(
    callback: CallbackQuery,
    list_status: str,
    list_page: int,
    video_id: int,
) -> None:
    """Рендерит детальную карточку заявки в админке."""

    repository = BotRepository(get_session_factory())
    video = await repository.get_video_with_user(video_id)
    if video is None:
        await safe_edit_admin_text(
            callback,
            "Заявка не найдена.",
            get_admin_dashboard_keyboard(),
        )
        return

    await safe_edit_admin_text(
        callback,
        build_admin_detail_text(video),
        get_admin_detail_keyboard(
            video_id=video.video_id,
            current_status=video.status,
            back_status=list_status,
            back_page=list_page,
            can_mark_paid=has_payment_details(video.user),
        ),
    )


async def render_admin_detail_message(
    bot: Bot,
    video_id: int,
    back_status: object,
    back_page: object,
    chat_id: object,
    message_id: object,
) -> None:
    """Обновляет сообщение с детальной карточкой заявки."""

    if not isinstance(chat_id, int) or not isinstance(message_id, int):
        return

    repository = BotRepository(get_session_factory())
    video = await repository.get_video_with_user(video_id)
    if video is None:
        return
    normalized_back_status = normalize_status(back_status)
    safe_back_page = normalize_page(back_page)
    if normalized_back_status is None:
        normalized_back_status = video.status

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=build_admin_detail_text(video),
        reply_markup=get_admin_detail_keyboard(
            video_id=video.video_id,
            current_status=video.status,
            back_status=normalized_back_status,
            back_page=safe_back_page,
            can_mark_paid=has_payment_details(video.user),
        ),
        disable_web_page_preview=True,
    )


def build_admin_list_text(status: str, videos: list[Video]) -> str:
    """Формирует текст раздела админки со списком заявок."""

    title = SECTION_TITLES.get(status, f"{LIST_TEXT} <b>Заявки</b>")
    if not videos:
        return f"{title}\n\nВ этом разделе пока нет заявок."
    return f"{title}\n\nВыберите заявку из списка ниже."


def build_admin_list_items(videos: list[Video]) -> list[tuple[int, str]]:
    """Собирает короткие подписи кнопок списка заявок."""

    items: list[tuple[int, str]] = []
    for video in videos:
        username = "без @"
        if video.user is not None and video.user.username:
            username = f"@{video.user.username}"
        platform = PLATFORM_LABELS.get(video.platform, video.platform)
        title = shorten_admin_title(video.title or video.url)
        payment_marker = ""
        if video.status == APPROVED_STATUS:
            payment_marker = " | рекв. есть" if has_payment_details(video.user) else " | нет рекв."
        label = f"#{video.video_id:05d} {platform} | {username}{payment_marker} | {title}"
        items.append((video.video_id, label))
    return items


def build_admin_all_videos_text(videos: list[Video]) -> str:
    """Формирует текст истории всех видео для админской панели."""

    title = SECTION_TITLES["all"]
    if not videos:
        return f"{title}\n\nВ этом разделе пока нет видео."
    cards = [format_admin_all_video_card(video) for video in videos]
    return f"{title}\n\n" + "\n\n".join(cards)


def format_admin_all_video_card(video: Video) -> str:
    """Формирует карточку видео для общего админского списка."""

    username = "без username"
    if video.user is not None and video.user.username:
        username = f"@{video.user.username}"
    platform = PLATFORM_LABELS.get(video.platform, video.platform)
    title = shorten_video_title(video.title or video.url)
    return (
        f"<b>Пользователь:</b> {username}\n"
        f"<b>Название:</b> <a href=\"{video.url}\">{title}</a>\n"
        f"<b>Платформа:</b> {platform}\n"
        f"<b>Дата добавления:</b> {format_datetime(video.created_at)}\n"
        f"<b>Просмотры:</b> {format_views_count(video.views_count)}"
    )


def build_admin_detail_text(video: Video) -> str:
    """Формирует подробную карточку заявки для админ-панели."""

    username = "без username"
    if video.user is not None and video.user.username:
        username = f"@{video.user.username}"

    status = STATUS_LABELS.get(video.status, video.status)
    platform = PLATFORM_LABELS.get(video.platform, video.platform)
    payment_method = format_payment_method(getattr(video.user, "payment_method", None))
    payment_details = build_admin_payment_details(video.user)
    text = (
        f"{INBOX_TEXT} <b>Заявка #{video.video_id:05d}</b>\n\n"
        f"<b>Пользователь:</b> {username} (id: {video.user_id})\n"
        f"<b>Видео:</b> <a href=\"{video.url}\">{shorten_video_title(video.title or video.url)}</a>\n"
        f"<b>Платформа:</b> {platform}\n"
        f"<b>Дата:</b> {format_datetime(video.created_at)}\n"
        f"<b>Просмотры:</b> {format_views_count(video.views_count)}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Сумма выплаты:</b> {int(video.payout_amount)} ₽\n"
        f"<b>Способ вывода:</b> {payment_method}\n"
        f"<b>Реквизиты:</b> <code>{escape(payment_details)}</code>"
    )
    if video.status == APPROVED_STATUS and not has_payment_details(video.user):
        text += (
            "\n\n"
            "<b>Статус выплаты:</b> ожидаем добавление реквизитов.\n"
            "После добавления реквизитов администраторам придёт уведомление."
        )
    if video.reject_reason:
        text += (
            "\n<b>Причина отказа:</b>\n"
            f"<blockquote>{video.reject_reason}</blockquote>"
        )
    return text


def parse_video_id(callback_data: str | None) -> int | None:
    """Извлекает video_id из callback data."""

    if not callback_data:
        return None
    parts = callback_data.split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def parse_status_from_menu(callback_data: str | None) -> str | None:
    """Извлекает статус раздела из callback главного меню админки."""

    if not callback_data:
        return None
    parts = callback_data.split(":")
    if len(parts) != 3:
        return None
    return normalize_status(parts[2])


def parse_admin_list_callback(callback_data: str | None) -> tuple[str | None, int]:
    """Извлекает статус и страницу списка админки."""

    if not callback_data:
        return None, 1
    parts = callback_data.split(":")
    if len(parts) != 4:
        return None, 1
    status = normalize_status(parts[2])
    try:
        page = max(int(parts[3]), 1)
    except ValueError:
        return status, 1
    return status, page


def parse_all_videos_page(callback_data: str | None) -> int:
    """Извлекает номер страницы из callback общего списка видео."""

    if not callback_data:
        return 1
    parts = callback_data.split(":")
    if len(parts) != 3:
        return 1
    try:
        return max(int(parts[2]), 1)
    except ValueError:
        return 1


def parse_admin_view_callback(
    callback_data: str | None,
) -> tuple[str | None, int, int | None]:
    """Извлекает статус, страницу и video_id из детальной кнопки."""

    if not callback_data:
        return None, 1, None
    parts = callback_data.split(":")
    if len(parts) != 5:
        return None, 1, None
    status = normalize_status(parts[2])
    try:
        page = max(int(parts[3]), 1)
        video_id = int(parts[4])
    except ValueError:
        return status, 1, None
    return status, page, video_id


def parse_action_context(callback_data: str | None) -> tuple[str | None, int]:
    """Извлекает контекст раздела для действий из детальной карточки."""

    if not callback_data:
        return None, 1
    parts = callback_data.split(":")
    if len(parts) != 5:
        return None, 1
    status = normalize_status(parts[3])
    try:
        page = max(int(parts[4]), 1)
    except ValueError:
        return status, 1
    return status, page


def parse_payout_amount(value: str) -> float | None:
    """Преобразует введённую сумму в число."""

    normalized = value.strip().replace(",", ".")
    try:
        amount = float(normalized)
    except ValueError:
        return None
    if amount <= 0:
        return None
    return round(amount, 2)


async def is_valid_admin_callback(callback: CallbackQuery) -> bool:
    """Проверяет, что callback пришёл от авторизованного администратора."""

    if callback.from_user is None:
        return False
    if await has_active_admin_session(callback.from_user.id):
        return True
    await callback.answer(ADMIN_SESSION_REQUIRED_TEXT, show_alert=True)
    return False


async def is_valid_admin_message(message: Message) -> bool:
    """Проверяет, что сообщение пришло от авторизованного администратора."""

    if message.from_user is None:
        return False
    if await has_active_admin_session(message.from_user.id):
        return True
    await message.answer(ADMIN_SESSION_REQUIRED_TEXT)
    return False


async def has_active_admin_session(user_id: int) -> bool:
    """Проверяет, что администратор вошёл в панель и сессия активна."""

    repository = BotRepository(get_session_factory())
    user = await repository.get_user(user_id)
    return bool(user and user.is_admin_session)


async def is_video_in_status(video_id: int, status: str) -> bool:
    """Проверяет, что заявка находится в ожидаемом статусе."""

    repository = BotRepository(get_session_factory())
    video = await repository.get_video(video_id)
    return bool(video and video.status == status)


def normalize_status(value: str | None) -> str | None:
    """Проверяет, что статус относится к допустимым разделам админки."""

    if value not in SECTION_TITLES:
        return None
    return value


def normalize_page(value: object) -> int:
    """Возвращает безопасный номер страницы для админской панели."""

    if isinstance(value, int):
        return max(value, 1)
    return 1


def shorten_admin_title(value: str) -> str:
    """Укорачивает название видео для кнопки в списке."""

    normalized = value.strip()
    if len(normalized) <= ADMIN_TITLE_LENGTH:
        return normalized
    return f"{normalized[:ADMIN_TITLE_LENGTH].rstrip()}..."


def has_payment_details(user: User | None) -> bool:
    """Проверяет, что у пользователя привязаны реквизиты."""

    return bool(user and user.payment_method and user.payment_details)


def build_admin_payment_details(user: User | None) -> str:
    """Возвращает реквизиты для детальной карточки администратора."""

    if not has_payment_details(user):
        return PAYMENT_DETAILS_EMPTY_TEXT
    return user.payment_details or PAYMENT_DETAILS_EMPTY_TEXT


async def safe_edit_admin_text(
    callback: CallbackQuery,
    text: str,
    reply_markup: object,
) -> None:
    """Безопасно редактирует сообщение в админке."""

    if callback.message is None:
        return
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return
        raise


def get_chat_id(callback: CallbackQuery) -> int | None:
    """Возвращает chat_id исходного сообщения."""

    if callback.message is None:
        return None
    return callback.message.chat.id


def get_message_id(callback: CallbackQuery) -> int | None:
    """Возвращает message_id исходного сообщения."""

    if callback.message is None:
        return None
    return callback.message.message_id


def get_paid_error_text(error_text: str) -> str:
    """Преобразует техническую ошибку выплаты в понятный текст."""

    if "has no payment details" in error_text:
        return "У пользователя не привязаны реквизиты."
    if "must be in status approved" in error_text:
        return "Заявка уже не ждёт выплату."
    return "Не удалось подтвердить выплату."


def get_moderation_error_text(error_text: str) -> str:
    """Преобразует техническую ошибку модерации в понятный текст."""

    if "must be in status pending" in error_text:
        return "Заявка уже обработана."
    if "not found" in error_text:
        return "Заявка не найдена."
    return "Не удалось обработать заявку."


def format_datetime(value: datetime) -> str:
    """Форматирует дату заявки для админского сообщения."""

    return value.strftime("%d.%m.%Y %H:%M")


def format_views_count(value: int) -> str:
    """Форматирует число просмотров для интерфейса администратора."""

    return f"{max(value, 0):,}".replace(",", " ")
