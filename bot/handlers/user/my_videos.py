from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.db import BotRepository, Video, VideoStatus, get_session_factory
from bot.handlers.user.start import WELCOME_TEXT, show_callback_screen
from bot.keyboards.user_kb import get_main_menu_keyboard, get_my_videos_keyboard
from bot.services.telegram_safe import safe_callback_answer
from bot.services.video import shorten_video_title
from bot.ui.emojis import CLIPS_TEXT

router = Router(name="user.my_videos")

NO_VIDEOS_TEXT = (
    f"{CLIPS_TEXT} <b>Мои видео</b>\n\n"
    "У вас пока нет отправленных заявок."
)

STATUS_LABELS = {
    VideoStatus.PENDING.value: "На рассмотрении",
    VideoStatus.APPROVED.value: "Ожидает выплаты",
    VideoStatus.REJECTED.value: "Отклонено",
    VideoStatus.PAID.value: "Оплачено",
}
PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
}
@router.callback_query(F.data == "menu:my_videos")
async def show_my_videos(callback: CallbackQuery) -> None:
    """Показывает первую страницу истории видео пользователя."""

    await safe_callback_answer(callback)
    await render_videos_page(callback, page=1)


@router.callback_query(F.data.startswith("videos:page:"))
async def paginate_my_videos(callback: CallbackQuery) -> None:
    """Переключает страницы истории видео."""

    await safe_callback_answer(callback)
    page = parse_page_number(callback.data)
    await render_videos_page(callback, page=page)


@router.callback_query(F.data == "videos:noop")
async def ignore_videos_page_label(callback: CallbackQuery) -> None:
    """Тихо подтверждает нажатие на индикатор страницы."""

    await safe_callback_answer(callback)


@router.callback_query(F.data == "videos:back")
async def return_from_my_videos(callback: CallbackQuery) -> None:
    """Возвращает пользователя из истории видео в меню."""

    await safe_callback_answer(callback)
    await show_callback_screen(
        callback,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


async def render_videos_page(callback: CallbackQuery, page: int) -> None:
    """Рендерит страницу истории видео."""

    if callback.from_user is None or callback.message is None:
        return

    repository = BotRepository(get_session_factory())
    total_videos = await repository.count_user_videos(callback.from_user.id)
    result = await repository.get_user_videos_page(
        user_id=callback.from_user.id,
        page=page,
    )
    if not result.items:
        await safe_edit_text(
            callback=callback,
            text=build_empty_videos_text(total_videos),
            reply_markup=get_my_videos_keyboard(
                page=1,
                total_pages=1,
                has_items=False,
            ),
        )
        return

    text = build_videos_text(result.items, total_videos)
    await safe_edit_text(
        callback=callback,
        text=text,
        reply_markup=get_my_videos_keyboard(
            page=result.page,
            total_pages=result.total_pages,
            has_items=True,
        ),
    )


def build_videos_text(videos: list[Video], total_videos: int) -> str:
    """Формирует текст списка заявок пользователя."""

    cards = [format_video_card(video) for video in videos]
    return (
        f"{CLIPS_TEXT} <b>Мои видео</b>\n\n"
        f"<b>Загружено видео:</b> {total_videos}\n\n"
        + "\n\n".join(cards)
    )


def build_empty_videos_text(total_videos: int) -> str:
    """Формирует пустой экран раздела с числом загруженных роликов."""

    return (
        f"{CLIPS_TEXT} <b>Мои видео</b>\n\n"
        f"<b>Загружено видео:</b> {total_videos}\n\n"
        "У вас пока нет отправленных заявок."
    )


def format_video_card(video: Video) -> str:
    """Формирует карточку одной заявки."""

    title = shorten_title(video.title or video.url)
    platform = PLATFORM_LABELS.get(video.platform, video.platform)
    date_label = format_date(video.created_at)
    status = STATUS_LABELS.get(video.status, video.status)
    lines = [
        f"<b>Название:</b> <a href=\"{video.url}\">{title}</a>",
        f"<b>Платформа:</b> {platform}",
        f"<b>Дата добавления:</b> {date_label}",
        f"<b>Просмотры:</b> {format_views_count(video.views_count)}",
        f"<b>Статус:</b> {status}",
        f"<b>Сумма выплаты:</b> {int(video.payout_amount)} ₽",
    ]
    if video.reject_reason:
        lines.append("<b>Причина отказа:</b>")
        lines.append(f"<blockquote>{video.reject_reason}</blockquote>")
    return "\n".join(lines)


def format_date(value: datetime) -> str:
    """Форматирует дату для пользовательского интерфейса."""

    return value.strftime("%d.%m.%Y")


def shorten_title(value: str) -> str:
    """Ограничивает длину названия для компактного отображения."""

    return shorten_video_title(value)


def format_views_count(value: int) -> str:
    """Форматирует число просмотров с пробелами между разрядами."""

    return f"{max(value, 0):,}".replace(",", " ")


def parse_page_number(callback_data: str | None) -> int:
    """Безопасно извлекает номер страницы из callback data."""

    if not callback_data:
        return 1
    parts = callback_data.split(":")
    if len(parts) != 3:
        return 1
    try:
        return max(int(parts[2]), 1)
    except ValueError:
        return 1


async def safe_edit_text(
    callback: CallbackQuery,
    text: str,
    reply_markup: object,
) -> None:
    """Показывает страницу с fallback на новое сообщение."""

    await show_callback_screen(
        callback,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
