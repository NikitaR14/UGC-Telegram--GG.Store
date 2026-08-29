from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services import video_monitor
from bot.services.video import VideoMetrics


def build_video(**overrides) -> SimpleNamespace:
    """Создаёт тестовый объект видео для мониторинга просмотров."""

    payload = {
        "video_id": 17,
        "url": "https://youtube.com/shorts/example",
        "last_notified_threshold": 0,
        "status": "confirmed",
        "views_count": 0,
        "payout_notified_at": None,
        "user": SimpleNamespace(user_id=101, username="creator"),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class DummyRepository:
    """Сохраняет последние аргументы обновления видео."""

    def __init__(self) -> None:
        self.updated_payload: tuple[int, int, int | None] | None = None
        self.touched_video_id: int | None = None
        self.payout_notified_video_id: int | None = None
        self.video = build_video(video_id=33)

    async def update_video_metrics(
        self,
        video_id: int,
        views_count: int,
        likes_count: int | None = None,
        comments_count: int | None = None,
        shares_count: int | None = None,
        last_notified_threshold: int | None = None,
    ):
        self.updated_payload = (video_id, views_count, last_notified_threshold)
        return build_video(
            video_id=video_id,
            views_count=views_count,
            last_notified_threshold=last_notified_threshold or 0,
        )

    async def mark_payout_notification_sent(self, video_id: int) -> None:
        self.payout_notified_video_id = video_id

    async def get_video_with_user(self, video_id: int):
        if self.video.video_id != video_id:
            return None
        return self.video

    async def touch_video_views_refresh(self, video_id: int) -> None:
        self.touched_video_id = video_id


@pytest.mark.asyncio
async def test_refresh_single_video_views_updates_views_and_sends_notifications(
    monkeypatch,
) -> None:
    """Проверяет happy-path обновления просмотров и уведомлений."""

    repository = DummyRepository()
    user_calls: list[int] = []
    admin_calls: list[int] = []

    async def fake_fetch(url: str) -> VideoMetrics:
        return VideoMetrics(views_count=100000, likes_count=50)

    async def fake_notify_user(bot, user, threshold: int) -> None:
        user_calls.append(threshold)

    async def fake_notify_admins(bot, user, video) -> bool:
        admin_calls.append(video.video_id)
        return True

    monkeypatch.setattr(video_monitor, "fetch_video_metrics", fake_fetch)
    monkeypatch.setattr(video_monitor, "notify_video_views_milestone", fake_notify_user)
    monkeypatch.setattr(
        video_monitor,
        "notify_admins_about_video_views_milestone",
        fake_notify_admins,
    )

    await video_monitor.refresh_single_video_views(
        bot=object(),
        repository=repository,
        video=build_video(),
    )

    assert repository.updated_payload == (17, 100000, 100000)
    assert user_calls == [100000]
    assert admin_calls == [17]
    assert repository.payout_notified_video_id == 17


@pytest.mark.asyncio
async def test_refresh_single_video_views_keeps_previous_state_on_fetch_error(
    monkeypatch,
) -> None:
    """Проверяет отсутствие обновления при неудачном получении просмотров."""

    repository = DummyRepository()

    async def fake_fetch(url: str) -> int | None:
        return None

    monkeypatch.setattr(video_monitor, "fetch_video_metrics", fake_fetch)

    await video_monitor.refresh_single_video_views(
        bot=object(),
        repository=repository,
        video=build_video(),
    )

    assert repository.updated_payload is None
    assert repository.touched_video_id == 17


@pytest.mark.asyncio
async def test_payout_notification_is_retried_when_no_admin_received_it(
    monkeypatch,
) -> None:
    """Проверяет, что неуспешная доставка не фиксируется как отправленная."""

    repository = DummyRepository()

    async def fake_notify_admins(bot, user, video) -> bool:
        return False

    monkeypatch.setattr(
        video_monitor,
        "notify_admins_about_video_views_milestone",
        fake_notify_admins,
    )

    await video_monitor.notify_payout_ready_if_needed(
        object(),
        repository,
        build_video().user,
        build_video(views_count=100_000),
    )

    assert repository.payout_notified_video_id is None


def test_get_highest_reached_threshold_returns_max_new_milestone() -> None:
    """Проверяет выбор только максимального нового порога просмотров."""

    assert video_monitor.get_highest_reached_threshold(4999, 0) is None
    assert video_monitor.get_highest_reached_threshold(5000, 0) == 5000
    assert video_monitor.get_highest_reached_threshold(21000, 0) == 20000
    assert video_monitor.get_highest_reached_threshold(120000, 50000) == 100000


@pytest.mark.asyncio
async def test_refresh_video_views_now_uses_fresh_repository(
    monkeypatch,
) -> None:
    """Проверяет немедленное обновление просмотров для нового видео."""

    repository = DummyRepository()
    refresh_calls: list[int] = []

    async def fake_refresh_single(bot, current_repository, video) -> None:
        refresh_calls.append(video.video_id)
        assert current_repository is repository

    monkeypatch.setattr(video_monitor, "BotRepository", lambda _: repository)
    monkeypatch.setattr(video_monitor, "get_session_factory", lambda: None)
    monkeypatch.setattr(video_monitor, "refresh_single_video_views", fake_refresh_single)

    await video_monitor.refresh_video_views_now(object(), 33)

    assert refresh_calls == [33]
