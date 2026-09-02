from __future__ import annotations

import asyncio
from datetime import timedelta

from aiogram import Bot
from loguru import logger

from bot.db import BotRepository, User, Video, VideoStatus, get_session_factory
from bot.services.notification import (
    VIDEO_VIEWS_MILESTONES,
    notify_admins_about_video_views_milestone,
    notify_video_views_milestone,
)
from bot.services.video import fetch_video_metrics, is_instagram_cooldown_active

VIEWS_REFRESH_INTERVAL_SECONDS = 4 * 60 * 60
VIEWS_REFRESH_BATCH_SIZE = 100
VIEWS_MONITOR_POLL_INTERVAL_SECONDS = 5 * 60
INSTAGRAM_REFRESH_BATCH_SIZE = 2
INSTAGRAM_REFRESH_INTERVAL = timedelta(hours=12)


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
    regular_videos = await repository.get_videos_due_for_views_refresh(
        VIEWS_REFRESH_BATCH_SIZE,
        exclude_platform="instagram",
    )
    instagram_videos = await repository.get_videos_due_for_views_refresh(
        INSTAGRAM_REFRESH_BATCH_SIZE,
        platform="instagram",
        refresh_interval=INSTAGRAM_REFRESH_INTERVAL,
    )
    for video in [*instagram_videos, *regular_videos]:
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

    if video.platform == "instagram" and is_instagram_cooldown_active():
        return
    metrics = await fetch_video_metrics(video.url)
    if metrics is None:
        if video.platform == "instagram" and is_instagram_cooldown_active():
            return
        await repository.touch_video_views_refresh(video.video_id)
        return

    reached_threshold = None
    if video.status == VideoStatus.CONFIRMED.value:
        reached_threshold = get_highest_reached_threshold(
            metrics.views_count,
            video.last_notified_threshold,
        )
    updated_video = await repository.update_video_metrics(
        video.video_id,
        metrics.views_count,
        likes_count=metrics.likes_count,
        comments_count=metrics.comments_count,
        shares_count=metrics.shares_count,
        last_notified_threshold=reached_threshold or None,
    )
    if updated_video is None or video.user is None:
        return
    if reached_threshold is not None:
        await notify_video_views_milestone(bot, video.user, reached_threshold)
    await notify_payout_ready_if_needed(bot, repository, video.user, updated_video)


async def notify_payout_ready_if_needed(
    bot: Bot,
    repository: BotRepository,
    user: User,
    video: Video,
) -> None:
    """Уведомляет админов, когда подтверждённый ролик готов к выплате."""

    if video.status != VideoStatus.CONFIRMED.value:
        return
    if video.views_count < 100_000 or video.payout_notified_at is not None:
        return
    is_delivered = await notify_admins_about_video_views_milestone(bot, user, video)
    if is_delivered:
        await repository.mark_payout_notification_sent(video.video_id)


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
