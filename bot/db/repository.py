from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Optional

from sqlalchemy import Select, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.db.models import (
    DETAILS_TAIL_LENGTH,
    PaymentHistory,
    User,
    Video,
    VideoStatus,
    Withdrawal,
)

DEFAULT_PAGE_SIZE = 5
VIEWS_REFRESH_INTERVAL = timedelta(hours=4)


@dataclass(slots=True)
class PageResult:
    """Результат пагинации для списков пользователя."""

    items: list[Video] | list[Withdrawal] | list[PaymentHistory]
    page: int
    total_pages: int


class BotRepository:
    """Репозиторий с базовыми операциями бота поверх SQLAlchemy."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_user(self, user_id: int, username: Optional[str]) -> User:
        """Создаёт пользователя или обновляет его username."""

        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                user = User(user_id=user_id, username=username)
                session.add(user)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    user = await session.get(User, user_id)
                    if user is None:
                        raise
                    user.username = username
                    await session.commit()
            else:
                user.username = username
                await session.commit()
            await session.refresh(user)
            return user

    async def set_admin_session(self, user_id: int, is_admin_session: bool) -> None:
        """Обновляет флаг активной admin-сессии."""

        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                user = User(user_id=user_id, is_admin_session=is_admin_session)
                session.add(user)
            else:
                user.is_admin_session = is_admin_session
            await session.commit()

    async def save_payment_details(
        self,
        user_id: int,
        payment_method: str,
        payment_details: str,
    ) -> User:
        """Сохраняет реквизиты пользователя."""

        async with self._session_factory() as session:
            user = await self._require_user(session, user_id)
            user.payment_method = payment_method
            user.payment_details = payment_details
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user(self, user_id: int) -> User | None:
        """Возвращает пользователя по id или None, если его нет."""

        async with self._session_factory() as session:
            return await session.get(User, user_id)

    async def get_video(self, video_id: int) -> Video | None:
        """Возвращает заявку по id или None, если её нет."""

        async with self._session_factory() as session:
            return await session.get(Video, video_id)

    async def get_video_with_user(self, video_id: int) -> Video | None:
        """Возвращает заявку вместе со связанным пользователем."""

        async with self._session_factory() as session:
            query = (
                select(Video)
                .options(selectinload(Video.user))
                .where(Video.video_id == video_id)
            )
            return await session.scalar(query)

    async def create_video(
        self,
        user_id: int,
        url: str,
        platform: str,
        title: Optional[str] = None,
    ) -> Video:
        """Создаёт новую заявку со статусом pending."""

        async with self._session_factory() as session:
            await self._require_user(session, user_id)
            video = Video(user_id=user_id, url=url, platform=platform, title=title)
            session.add(video)
            await session.commit()
            await session.refresh(video)
            return video

    async def update_video_title(self, video_id: int, title: str) -> Video | None:
        """Обновляет название видео для существующей заявки."""

        async with self._session_factory() as session:
            video = await session.get(Video, video_id)
            if video is None:
                return None
            video.title = title
            await session.commit()
            await session.refresh(video)
            return video

    async def approve_video(self, video_id: int, payout_amount: float) -> Video:
        """Переводит заявку в approved и начисляет баланс пользователю."""

        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            self._ensure_video_status(video, VideoStatus.PENDING)
            user = await self._require_user(session, video.user_id)
            video.status = VideoStatus.APPROVED.value
            video.payout_amount = payout_amount
            video.reject_reason = None
            user.balance += payout_amount
            await session.commit()
            await session.refresh(video)
            return video

    async def reject_video(self, video_id: int, reason: str) -> Video:
        """Переводит заявку в rejected и сохраняет причину отказа."""

        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            self._ensure_video_status(video, VideoStatus.PENDING)
            video.status = VideoStatus.REJECTED.value
            video.reject_reason = reason
            await session.commit()
            await session.refresh(video)
            return video

    async def mark_video_paid(self, video_id: int) -> Withdrawal:
        """Фиксирует выплату по заявке и обновляет баланс пользователя."""

        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            self._ensure_video_status(video, VideoStatus.APPROVED)
            user = await self._require_user(session, video.user_id)
            if not user.payment_method or not user.payment_details:
                raise ValueError(
                    f"User {user.user_id} has no payment details for video {video.video_id}",
                )
            withdrawal = Withdrawal(
                user_id=user.user_id,
                video_id=video.video_id,
                amount=video.payout_amount,
                method=user.payment_method or "",
                details_tail=self._build_details_tail(user.payment_details),
            )
            payment_history = PaymentHistory(
                user_id=user.user_id,
                amount=video.payout_amount,
                method=user.payment_method or "",
                details=user.payment_details or "",
            )
            video.status = VideoStatus.PAID.value
            user.balance -= video.payout_amount
            user.total_withdrawn += video.payout_amount
            session.add(withdrawal)
            session.add(payment_history)
            await session.commit()
            await session.refresh(withdrawal)
            return withdrawal

    async def get_user_videos_page(
        self,
        user_id: int,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу заявок пользователя."""

        async with self._session_factory() as session:
            query = select(Video).where(Video.user_id == user_id)
            return await self._paginate(session, query, Video.created_at, page, page_size)

    async def get_user_withdrawals_page(
        self,
        user_id: int,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу истории выплат пользователя."""

        async with self._session_factory() as session:
            query = select(Withdrawal).where(Withdrawal.user_id == user_id)
            return await self._paginate(
                session,
                query,
                Withdrawal.paid_at,
                page,
                page_size,
            )

    async def get_user_payment_history_page(
        self,
        user_id: int,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу истории выплат из отдельной payment_history."""

        async with self._session_factory() as session:
            query = select(PaymentHistory).where(PaymentHistory.user_id == user_id)
            return await self._paginate(
                session,
                query,
                PaymentHistory.paid_at,
                page,
                page_size,
            )

    async def get_admin_videos_page(
        self,
        status: str,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу заявок для админской панели по статусу."""

        async with self._session_factory() as session:
            query = (
                select(Video)
                .options(selectinload(Video.user))
                .where(Video.status == status)
            )
            return await self._paginate(session, query, Video.created_at, page, page_size)

    async def get_all_videos_page(
        self,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу всех видео для отдельного админского раздела."""

        async with self._session_factory() as session:
            query = select(Video).options(selectinload(Video.user))
            return await self._paginate(session, query, Video.created_at, page, page_size)

    async def count_user_videos(self, user_id: int) -> int:
        """Считает общее количество загруженных видео пользователя."""

        async with self._session_factory() as session:
            query = select(func.count()).select_from(Video).where(Video.user_id == user_id)
            return int(await session.scalar(query) or 0)

    async def count_user_videos_by_status(self, user_id: int, status: str) -> int:
        """Считает количество заявок пользователя в указанном статусе."""

        async with self._session_factory() as session:
            query = select(func.count()).select_from(Video).where(
                Video.user_id == user_id,
                Video.status == status,
            )
            return int(await session.scalar(query) or 0)

    async def get_user_video_ids_by_status(self, user_id: int, status: str) -> list[int]:
        """Возвращает номера заявок пользователя в указанном статусе."""

        async with self._session_factory() as session:
            query = (
                select(Video.video_id)
                .where(
                    Video.user_id == user_id,
                    Video.status == status,
                )
                .order_by(desc(Video.created_at))
            )
            rows = await session.scalars(query)
            return list(rows)

    async def get_active_admin_ids(self) -> list[int]:
        """Возвращает id пользователей с активной admin-сессией."""

        async with self._session_factory() as session:
            query = select(User.user_id).where(User.is_admin_session.is_(True))
            rows = await session.scalars(query)
            return list(rows)

    async def get_videos_due_for_views_refresh(self, limit: int = 100) -> list[Video]:
        """Возвращает видео, для которых пора обновить счётчик просмотров."""

        cutoff = datetime.now(UTC) - VIEWS_REFRESH_INTERVAL
        async with self._session_factory() as session:
            query = (
                select(Video)
                .options(selectinload(Video.user))
                .where(Video.views_updated_at.is_(None) | (Video.views_updated_at <= cutoff))
                .order_by(Video.views_updated_at.asc().nullsfirst(), desc(Video.created_at))
                .limit(limit)
            )
            rows = await session.scalars(query)
            return list(rows)

    async def update_video_views(
        self,
        video_id: int,
        views_count: int,
        last_notified_threshold: int | None = None,
    ) -> Video | None:
        """Обновляет просмотры видео и служебные поля мониторинга."""

        async with self._session_factory() as session:
            video = await session.get(Video, video_id)
            if video is None:
                return None
            video.views_count = max(views_count, 0)
            video.views_updated_at = datetime.now(UTC)
            if last_notified_threshold is not None:
                video.last_notified_threshold = last_notified_threshold
            await session.commit()
            await session.refresh(video)
            return video

    async def touch_video_views_refresh(self, video_id: int) -> Video | None:
        """Фиксирует время последней попытки обновления просмотров."""

        async with self._session_factory() as session:
            video = await session.get(Video, video_id)
            if video is None:
                return None
            video.views_updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(video)
            return video

    async def _paginate(
        self,
        session: AsyncSession,
        query: Select[tuple[Video]] | Select[tuple[Withdrawal]],
        sort_column: object,
        page: int,
        page_size: int,
    ) -> PageResult:
        """Собирает страницу данных и метаинформацию пагинации."""

        safe_page = max(page, 1)
        total_items = await self._count_rows(session, query)
        total_pages = max(ceil(total_items / page_size), 1)
        current_page = min(safe_page, total_pages)
        rows = await session.scalars(
            query.order_by(desc(sort_column))
            .limit(page_size)
            .offset((current_page - 1) * page_size)
        )
        return PageResult(items=list(rows), page=current_page, total_pages=total_pages)

    async def _count_rows(
        self,
        session: AsyncSession,
        query: Select[tuple[Video]] | Select[tuple[Withdrawal]] | Select[tuple[PaymentHistory]],
    ) -> int:
        """Считает количество записей для пагинации."""

        subquery = query.subquery()
        count_query = select(func.count()).select_from(subquery)
        return int(await session.scalar(count_query) or 0)

    async def _require_user(self, session: AsyncSession, user_id: int) -> User:
        """Гарантирует наличие пользователя в базе."""

        user = await session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        return user

    async def _require_video(self, session: AsyncSession, video_id: int) -> Video:
        """Гарантирует наличие заявки в базе."""

        video = await session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")
        return video

    def _ensure_video_status(self, video: Video, expected_status: VideoStatus) -> None:
        """Проверяет, что заявка находится в ожидаемом статусе."""

        if video.status != expected_status.value:
            raise ValueError(
                f"Video {video.video_id} must be in status {expected_status.value}",
            )

    def _build_details_tail(self, payment_details: Optional[str]) -> str:
        """Возвращает последние 4 символа реквизитов или безопасную заглушку."""

        if not payment_details:
            return "----"
        return payment_details[-DETAILS_TAIL_LENGTH:].rjust(DETAILS_TAIL_LENGTH, "*")
