from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.db import BotRepository, get_session_factory
from bot.handlers.admin.moderation import notify_admins_about_video
from bot.handlers.user.start import WELCOME_TEXT, show_callback_screen
from bot.keyboards.user_kb import (
    get_add_video_keyboard,
    get_main_menu_keyboard,
    get_return_to_menu_keyboard,
)
from bot.services.metrika import MetrikaGoal, track_metrika_goal
from bot.services.telegram_safe import safe_callback_answer, safe_message_answer
from bot.services.video import is_fallback_title, detect_platform, resolve_video_title, resolve_video_title_quickly
from bot.services.video_monitor import refresh_video_views_now
from bot.ui.emojis import SUCCESS_TEXT, VIDEO_TEXT

router = Router(name="user.video")

REQUEST_VIDEO_TEXT = (
    f"{VIDEO_TEXT} Пришлите ссылку на вертикальный видеоролик.\n\n"
    "Поддерживаемые платформы:\n"
    "<blockquote>📺 TikTok, YouTube Shorts.</blockquote>\n\n"
    "Не забудьте добавить хэштег <b>#GGStoreUGCclips</b> при загрузке видео на хостинг!"
)
VIDEO_LINK_ERROR_TEXT = (
    '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji> '
    "Ссылка не распознана. Поддерживаются только TikTok и YouTube Shorts.\n"
    "Попробуйте ещё раз или нажмите «Назад»."
)


class AddVideoState(StatesGroup):
    """Состояния сценария добавления видео."""

    waiting_for_url = State()


@router.callback_query(F.data == "menu:add_video")
async def request_video_url(callback: CallbackQuery, state: FSMContext) -> None:
    """Открывает сценарий добавления видео."""

    repository = BotRepository(get_session_factory())
    user = await repository.upsert_user(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
    )
    asyncio.create_task(track_metrika_goal(user, MetrikaGoal.ADD_VIDEO))
    await safe_callback_answer(callback)
    await state.set_state(AddVideoState.waiting_for_url)
    await show_callback_screen(
        callback,
        REQUEST_VIDEO_TEXT,
        reply_markup=get_add_video_keyboard(),
    )


@router.callback_query(F.data == "video:add:back")
async def return_from_add_video(callback: CallbackQuery, state: FSMContext) -> None:
    """Возвращает пользователя из сценария добавления видео в меню."""

    await state.clear()
    await safe_callback_answer(callback)
    await show_callback_screen(
        callback,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(AddVideoState.waiting_for_url)
async def handle_video_url(message: Message, state: FSMContext) -> None:
    """Проверяет ссылку и создаёт заявку в базе."""

    if message.from_user is None:
        return

    if not message.text:
        await safe_message_answer(
            message,
            VIDEO_LINK_ERROR_TEXT,
            reply_markup=get_add_video_keyboard(),
        )
        return

    platform = detect_platform(message.text)
    if platform is None:
        await safe_message_answer(
            message,
            VIDEO_LINK_ERROR_TEXT,
            reply_markup=get_add_video_keyboard(),
        )
        return

    repository = BotRepository(get_session_factory())
    await repository.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    url = message.text.strip()
    title = await resolve_video_title_quickly(url, platform)
    video = await repository.create_video(
        user_id=message.from_user.id,
        url=url,
        platform=platform,
        title=title,
    )
    logger.info(
        "Video submitted | user={} url={} platform={}",
        message.from_user.id,
        url,
        platform,
    )
    await notify_admins_about_video(
        bot=message.bot,
        video=video,
        username=message.from_user.username,
    )
    await state.clear()
    await safe_message_answer(
        message,
        f"{SUCCESS_TEXT} Ссылка принята! Заявка "
        f"#{video.video_id:05d} отправлена на рассмотрение.\n"
        "Следить за статусом можно в разделе «Мои видео».",
        reply_markup=get_return_to_menu_keyboard(),
    )
    if is_fallback_title(title, url, platform):
        asyncio.create_task(enrich_video_title(video.video_id, url, platform))
    asyncio.create_task(refresh_video_views_now(message.bot, video.video_id))


async def enrich_video_title(video_id: int, url: str, platform: str) -> None:
    """Пытается фоново обновить fallback-название заявки на реальное."""

    resolved_title = await resolve_video_title(url, platform)
    if is_fallback_title(resolved_title, url, platform):
        return

    repository = BotRepository(get_session_factory())
    updated_video = await repository.update_video_title(video_id, resolved_title)
    if updated_video is None:
        return

    logger.info(
        "Video title updated in background | video_id={} title={}",
        video_id,
        resolved_title,
    )
