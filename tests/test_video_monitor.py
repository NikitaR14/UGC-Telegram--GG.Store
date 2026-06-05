from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.services import video_monitor


def build_video(**overrides) -> SimpleNamespace:
    """Создаёт тестовый объект видео для мониторинга просмотров."""

    payload = {
        "video_id": 17,
        "url": "https://youtube.com/shorts/example",
        "last_notified_threshold": 0,
        "user": SimpleNamespace(user_id=101, username="creator"),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class DummyRepository:
    """Сохраняет последние аргументы обновления видео."""

    def __init__(self) -> None:
        self.updated_payload: tuple[int, int, int | None] | None = None
        self.video = build_video(video_id=33)

    async def update_video_views(
        self,
        video_id: int,
        views_count: int,
        last_notified_threshold: int | None = None,
    ) -> None:
        self.updated_payload = (video_id, views_count, last_notified_threshold)

    async def get_video_with_user(self, video_id: int):
        if self.video.video_id != video_id:
            return None
        return self.video


@pytest.mark.asyncio
async def test_refresh_single_video_views_updates_views_and_sends_notifications(
    monkeypatch,
) -> None:
    """Проверяет happy-path обновления просмотров и уведомлений."""

    repository = DummyRepository()
    user_calls: list[int] = []
    admin_calls: list[int] = []

    async def fake_fetch(url: str) -> int:
        return 100000

    async def fake_notify_user(bot, user, threshold: int) -> None:
        user_calls.append(threshold)

    async def fake_notify_admins(bot, user, video) -> None:
        admin_calls.append(video.video_id)

    monkeypatch.setattr(video_monitor, "fetch_video_views", fake_fetch)
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


@pytest.mark.asyncio
async def test_refresh_single_video_views_keeps_previous_state_on_fetch_error(
    monkeypatch,
) -> None:
    """Проверяет отсутствие обновления при неудачном получении просмотров."""

    repository = DummyRepository()

    async def fake_fetch(url: str) -> int | None:
        return None

    monkeypatch.setattr(video_monitor, "fetch_video_views", fake_fetch)

    await video_monitor.refresh_single_video_views(
        bot=object(),
        repository=repository,
        video=build_video(),
    )

    assert repository.updated_payload is None


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
