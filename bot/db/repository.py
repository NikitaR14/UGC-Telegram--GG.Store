from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Optional

from sqlalchemy import Select, desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.db.models import (
    DETAILS_TAIL_LENGTH,
    MIN_WITHDRAWAL,
    PAYOUT_VIEWS_THRESHOLD,
    PaymentHistory,
    User,
    Video,
    VideoStatus,
    Withdrawal,
    WithdrawalRequest,
    WithdrawalRequestItem,
    WithdrawalRequestStatus,
)

DEFAULT_PAGE_SIZE = 5
VIEWS_REFRESH_INTERVAL = timedelta(hours=4)


@dataclass(slots=True)
class PageResult:
    """Результат пагинации для списков пользователя."""

    items: list[Video] | list[Withdrawal] | list[PaymentHistory] | list[WithdrawalRequest]
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
        """Одобряет выплату по подтверждённому ролику и начисляет баланс."""

        if payout_amount <= 0:
            raise ValueError("Payout amount must be positive")
        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            self._ensure_video_status(video, VideoStatus.CONFIRMED)
            if video.views_count < PAYOUT_VIEWS_THRESHOLD:
                raise ValueError(f"Video {video.video_id} has not reached payout threshold")
            user = await self._require_user(session, video.user_id)
            video.status = VideoStatus.APPROVED.value
            video.payout_amount = payout_amount
            video.reject_reason = None
            user.balance += payout_amount
            await session.commit()
            await session.refresh(video)
            return video

    async def confirm_video(self, video_id: int) -> Video:
        """Подтверждает оформление ролика без начисления денег."""

        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            self._ensure_video_status(video, VideoStatus.PENDING)
            video.status = VideoStatus.CONFIRMED.value
            video.reject_reason = None
            await session.commit()
            await session.refresh(video)
            return video

    async def reject_video(self, video_id: int, reason: str) -> Video:
        """Переводит заявку в rejected и сохраняет причину отказа."""

        async with self._session_factory() as session:
            video = await self._require_video(session, video_id)
            if video.status not in {
                VideoStatus.PENDING.value,
                VideoStatus.CONFIRMED.value,
            }:
                raise ValueError(
                    f"Video {video.video_id} must be in status pending or confirmed",
                )
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

        return await self.update_video_metrics(
            video_id=video_id,
            views_count=views_count,
            last_notified_threshold=last_notified_threshold,
        )

    async def update_video_metrics(
        self,
        video_id: int,
        views_count: int,
        likes_count: int | None = None,
        comments_count: int | None = None,
        shares_count: int | None = None,
        last_notified_threshold: int | None = None,
    ) -> Video | None:
        """Обновляет публичную статистику и служебные поля."""

        async with self._session_factory() as session:
            video = await session.get(Video, video_id)
            if video is None:
                return None
            video.views_count = max(views_count, 0)
            if likes_count is not None:
                video.likes_count = likes_count
            if comments_count is not None:
                video.comments_count = comments_count
            if shares_count is not None:
                video.shares_count = shares_count
            video.views_updated_at = datetime.now(UTC)
            if last_notified_threshold is not None:
                video.last_notified_threshold = last_notified_threshold
            await session.commit()
            await session.refresh(video)
            return video

    async def mark_payout_notification_sent(self, video_id: int) -> None:
        """Фиксирует отправку админского уведомления о выплате."""

        async with self._session_factory() as session:
            video = await session.get(Video, video_id)
            if video is None or video.payout_notified_at is not None:
                return
            video.payout_notified_at = datetime.now(UTC)
            await session.commit()

    async def get_user_eligible_videos_page(
        self,
        user_id: int,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает ролики, доступные для новой заявки на вывод."""

        async with self._session_factory() as session:
            query = select(Video).where(
                Video.user_id == user_id,
                Video.status == VideoStatus.APPROVED.value,
                Video.active_withdrawal_request_id.is_(None),
            )
            return await self._paginate(session, query, Video.created_at, page, page_size)

    async def get_user_videos_by_ids(self, user_id: int, video_ids: list[int]) -> list[Video]:
        """Возвращает указанные ролики одного пользователя."""

        if not video_ids:
            return []
        async with self._session_factory() as session:
            query = (
                select(Video)
                .where(Video.user_id == user_id, Video.video_id.in_(video_ids))
                .order_by(desc(Video.created_at))
            )
            return list(await session.scalars(query))

    async def create_withdrawal_request(
        self,
        user_id: int,
        video_ids: list[int],
    ) -> WithdrawalRequest:
        """Создаёт общую заявку и резервирует выбранные ролики."""

        unique_ids = list(dict.fromkeys(video_ids))
        if not unique_ids:
            raise ValueError("Withdrawal request requires at least one video")
        async with self._session_factory() as session:
            user = await self._require_user(session, user_id)
            if not user.payment_method or not user.payment_details:
                raise ValueError(f"User {user_id} has no payment details")
            query = select(Video).where(
                Video.video_id.in_(unique_ids),
                Video.user_id == user_id,
                Video.status == VideoStatus.APPROVED.value,
                Video.active_withdrawal_request_id.is_(None),
            ).with_for_update()
            videos = list(await session.scalars(query))
            if len(videos) != len(unique_ids):
                raise ValueError("Some videos are not available for withdrawal")
            total_amount = round(sum(video.payout_amount for video in videos), 2)
            if total_amount < MIN_WITHDRAWAL:
                raise ValueError("Withdrawal amount is below minimum")
            request = WithdrawalRequest(
                user_id=user_id,
                total_amount=total_amount,
                method=user.payment_method,
                payment_details=user.payment_details,
                details_tail=self._build_details_tail(user.payment_details),
            )
            session.add(request)
            await session.flush()
            for video in videos:
                video.active_withdrawal_request_id = request.request_id
                session.add(
                    WithdrawalRequestItem(
                        request_id=request.request_id,
                        video_id=video.video_id,
                        amount=video.payout_amount,
                    ),
                )
            await session.commit()
            await session.refresh(request)
            return request

    async def get_withdrawal_request(self, request_id: int) -> WithdrawalRequest | None:
        """Возвращает заявку с пользователем и роликами."""

        async with self._session_factory() as session:
            query = (
                select(WithdrawalRequest)
                .options(
                    selectinload(WithdrawalRequest.user),
                    selectinload(WithdrawalRequest.items).selectinload(
                        WithdrawalRequestItem.video,
                    ),
                )
                .where(WithdrawalRequest.request_id == request_id)
            )
            return await session.scalar(query)

    async def get_admin_withdrawal_requests_page(
        self,
        status: str,
        page: int,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult:
        """Возвращает страницу общих заявок для админа."""

        async with self._session_factory() as session:
            query = (
                select(WithdrawalRequest)
                .options(selectinload(WithdrawalRequest.user))
                .where(WithdrawalRequest.status == status)
            )
            return await self._paginate(
                session,
                query,
                WithdrawalRequest.created_at,
                page,
                page_size,
            )

    async def pay_withdrawal_request(self, request_id: int) -> WithdrawalRequest:
        """Атомарно оплачивает общую заявку и все её ролики."""

        async with self._session_factory() as session:
            request = await self._require_withdrawal_request(session, request_id)
            self._ensure_withdrawal_status(request, WithdrawalRequestStatus.PENDING)
            user = await self._require_user(session, request.user_id)
            if user.balance < request.total_amount:
                raise ValueError("User balance is below withdrawal amount")
            items = list(
                await session.scalars(
                    select(WithdrawalRequestItem)
                    .options(selectinload(WithdrawalRequestItem.video))
                    .where(WithdrawalRequestItem.request_id == request_id),
                ),
            )
            for item in items:
                self._prepare_paid_withdrawal(session, request, item)
            request.status = WithdrawalRequestStatus.PAID.value
            request.paid_at = datetime.now(UTC)
            user.balance -= request.total_amount
            user.total_withdrawn += request.total_amount
            session.add(
                PaymentHistory(
                    user_id=user.user_id,
                    amount=request.total_amount,
                    method=request.method,
                    details=request.payment_details,
                ),
            )
            await session.commit()
            await session.refresh(request)
            return request

    async def reject_withdrawal_request(
        self,
        request_id: int,
        reason: str,
    ) -> WithdrawalRequest:
        """Отклоняет общую заявку и освобождает её ролики."""

        async with self._session_factory() as session:
            request = await self._require_withdrawal_request(session, request_id)
            self._ensure_withdrawal_status(request, WithdrawalRequestStatus.PENDING)
            request.status = WithdrawalRequestStatus.REJECTED.value
            request.reject_reason = reason
            await session.execute(
                update(Video)
                .where(Video.active_withdrawal_request_id == request_id)
                .values(active_withdrawal_request_id=None),
            )
            await session.commit()
            await session.refresh(request)
            return request

    async def get_videos_for_export(
        self,
        created_from: datetime,
        created_to: datetime,
    ) -> list[Video]:
        """Возвращает кандидатов для админского экспорта."""

        statuses = (
            VideoStatus.CONFIRMED.value,
            VideoStatus.APPROVED.value,
            VideoStatus.PAID.value,
        )
        async with self._session_factory() as session:
            query = (
                select(Video)
                .options(selectinload(Video.user))
                .where(
                    Video.status.in_(statuses),
                    Video.created_at >= created_from,
                    Video.created_at < created_to,
                )
                .order_by(User.username, Video.created_at)
                .join(Video.user)
            )
            return list(await session.scalars(query))

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
        query: Select[tuple[object]],
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
        query: Select[tuple[object]],
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

    async def _require_withdrawal_request(
        self,
        session: AsyncSession,
        request_id: int,
    ) -> WithdrawalRequest:
        """Гарантирует наличие общей заявки на вывод."""

        request = await session.get(WithdrawalRequest, request_id)
        if request is None:
            raise ValueError(f"Withdrawal request {request_id} not found")
        return request

    def _ensure_withdrawal_status(
        self,
        request: WithdrawalRequest,
        expected_status: WithdrawalRequestStatus,
    ) -> None:
        """Проверяет статус общей заявки."""

        if request.status != expected_status.value:
            raise ValueError(
                f"Withdrawal request {request.request_id} must be in status "
                f"{expected_status.value}",
            )

    def _prepare_paid_withdrawal(
        self,
        session: AsyncSession,
        request: WithdrawalRequest,
        item: WithdrawalRequestItem,
    ) -> None:
        """Готовит один ролик к оплате в общей транзакции."""

        video = item.video
        if video.status != VideoStatus.APPROVED.value:
            raise ValueError(f"Video {video.video_id} is not approved")
        if video.active_withdrawal_request_id != request.request_id:
            raise ValueError(f"Video {video.video_id} is not reserved by request")
        video.status = VideoStatus.PAID.value
        session.add(
            Withdrawal(
                user_id=request.user_id,
                video_id=video.video_id,
                amount=item.amount,
                method=request.method,
                details_tail=request.details_tail,
            ),
        )

    def _build_details_tail(self, payment_details: Optional[str]) -> str:
        """Возвращает последние 4 символа реквизитов или безопасную заглушку."""

        if not payment_details:
            return "----"
        return payment_details[-DETAILS_TAIL_LENGTH:].rjust(DETAILS_TAIL_LENGTH, "*")
