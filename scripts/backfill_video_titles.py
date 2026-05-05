from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select

from bot.db.models import Video
from bot.db.session import close_database, get_session_factory
from bot.services.video import is_fallback_title, resolve_video_title


async def main() -> None:
    """Обновляет старые fallback-заголовки видео на реальные названия."""

    session_factory = get_session_factory()
    updated_count = 0

    async with session_factory() as session:
        videos = list(
            await session.scalars(
                select(Video).order_by(Video.video_id.asc()),
            ),
        )
        for video in videos:
            if not is_fallback_title(video.title, video.url, video.platform):
                continue
            resolved_title = await resolve_video_title(video.url, video.platform)
            if is_fallback_title(resolved_title, video.url, video.platform):
                continue
            video.title = resolved_title
            updated_count += 1

        await session.commit()

    logger.info("Video titles backfilled | updated={}", updated_count)
    await close_database()


if __name__ == "__main__":
    asyncio.run(main())
