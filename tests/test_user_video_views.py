from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from bot.handlers.user import my_videos
from bot.handlers.user import video as user_video


def build_video(**overrides) -> SimpleNamespace:
    """Создаёт тестовую заявку пользователя для рендера списка."""

    payload = {
        "video_id": 1,
        "url": "https://youtube.com/shorts/abc123",
        "platform": "youtube",
        "title": "Тестовый ролик",
        "views_count": 54321,
        "status": "approved",
        "payout_amount": 1500.0,
        "reject_reason": None,
        "created_at": datetime(2026, 5, 4, 12, 0, 0),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_format_video_card_includes_views_count() -> None:
    """Проверяет отображение просмотров в карточке пользователя."""

    text = my_videos.format_video_card(build_video())

    assert "Просмотры" in text
    assert "54 321" in text


def test_build_videos_text_uses_updated_header() -> None:
    """Проверяет заголовок списка пользовательских видео."""

    text = my_videos.build_videos_text([build_video()], total_videos=7)

    assert "Мои видео" in text
    assert "Загружено видео:</b> 7" in text
    assert "Тестовый ролик" in text


def test_request_video_text_mentions_hashtag() -> None:
    """Проверяет обновлённый текст экрана добавления видео."""

    assert "#GGStoreUGCclips" in user_video.REQUEST_VIDEO_TEXT


def test_build_empty_videos_text_shows_uploaded_counter() -> None:
    """Проверяет счётчик видео на пустом экране раздела."""

    text = my_videos.build_empty_videos_text(0)

    assert "Загружено видео:</b> 0" in text
