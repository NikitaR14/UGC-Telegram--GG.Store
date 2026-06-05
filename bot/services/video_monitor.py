from __future__ import annotations

import asyncio

from aiogram import Bot
from loguru import logger

from bot.db import BotRepository, Video, get_session_factory
from bot.services.notification import (
    VIDEO_VIEWS_MILESTONES,
    notify_admins_about_video_views_milestone,
    notify_video_views_milestone,
)
from bot.services.video import fetch_video_views

VIEWS_REFRESH_INTERVAL_SECONDS = 4 * 60 * 60
VIEWS_REFRESH_BATCH_SIZE = 100
VIEWS_MONITOR_POLL_INTERVAL_SECONDS = 5 * 60


async def run_video_views_monitor(bot: Bot) -> None:
    """Запускает бесконечный цикл обновления просмотров видео."""

    while True:
        try:
            await refresh_due_video_views(bot)
        except Exception as error:
            logger.warning("Video views monitor failed | error={}", str(error))
        await asyncio.sleep(VIEWS_MONITOR_POLL_INTERVAL_SECONDS)


async def refresh_due_video_views(bot: Bot) -> None:
    """Обновляет просмотры у видео, для которых подошёл срок проверки."""

    repository = BotRepository(get_session_factory())
    videos = await repository.get_videos_due_for_views_refresh(VIEWS_REFRESH_BATCH_SIZE)
    for video in videos:
        await refresh_single_video_views(bot, repository, video)


async def refresh_video_views_now(bot: Bot, video_id: int) -> None:
    """Обновляет просмотры конкретного нового видео без ожидания общего цикла."""

    repository = BotRepository(get_session_factory())
    video = await repository.get_video_with_user(video_id)
    if video is None:
        return
    await refresh_single_video_views(bot, repository, video)


async def refresh_single_video_views(
    bot: Bot,
    repository: BotRepository,
    video: Video,
) -> None:
    """Обновляет просмотры одного видео и отправляет нужные уведомления."""

    views_count = await fetch_video_views(video.url)
    if views_count is None:
        await repository.touch_video_views_refresh(video.video_id)
        return

    reached_threshold = get_highest_reached_threshold(
        views_count,
        video.last_notified_threshold,
    )
    await repository.update_video_views(
        video.video_id,
        views_count,
        last_notified_threshold=reached_threshold or None,
    )
    if reached_threshold is None or video.user is None:
        return

    await notify_video_views_milestone(bot, video.user, reached_threshold)
    if reached_threshold >= 100000:
        await notify_admins_about_video_views_milestone(bot, video.user, video)


def get_highest_reached_threshold(
    views_count: int,
    last_notified_threshold: int,
) -> int | None:
    """Возвращает максимальный новый пройденный порог просмотров."""

    reached_thresholds = [
        threshold
        for threshold in VIDEO_VIEWS_MILESTONES
        if last_notified_threshold < threshold <= views_count
    ]
    if not reached_thresholds:
        return None
    return max(reached_thresholds)
