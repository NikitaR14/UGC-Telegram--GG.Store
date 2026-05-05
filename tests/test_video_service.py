from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.services import video as video_service


def test_detect_platform_supports_tiktok_and_youtube_shorts() -> None:
    """Проверяет распознавание поддерживаемых платформ по URL."""

    assert video_service.detect_platform("https://www.tiktok.com/@user/video/123") == "tiktok"
    assert video_service.detect_platform("https://youtube.com/shorts/abc123") == "youtube"
    assert video_service.detect_platform("https://youtu.be/abc123") == "youtube"
    assert video_service.detect_platform("https://example.com/video") is None


def test_build_video_title_shortens_long_path() -> None:
    """Проверяет безопасный fallback-заголовок из URL."""

    title = video_service.build_video_title(
        "https://youtube.com/shorts/abcdefghijklmnopqrstuvwxyz1234567890",
        "youtube",
    )

    assert title.startswith("youtube.com/shorts/")
    assert title.endswith("...")


def test_normalize_title_removes_platform_suffixes() -> None:
    """Проверяет очистку названия от хвостов платформ."""

    assert video_service.normalize_title("Крутое видео - YouTube") == "Крутое видео"
    assert video_service.normalize_title("Новый ролик | TikTok") == "Новый ролик"
    assert video_service.normalize_title("   ") is None


def test_extract_title_from_html_prefers_first_matching_pattern() -> None:
    """Проверяет извлечение названия из HTML-мета-тегов."""

    html = """
    <html>
      <head>
        <meta property="og:title" content="Тестовый ролик - YouTube">
        <title>Запасной заголовок</title>
      </head>
    </html>
    """

    assert video_service.extract_title_from_html(html) == "Тестовый ролик"


@pytest.mark.asyncio
async def test_resolve_video_title_returns_ytdlp_title_first(monkeypatch) -> None:
    """Проверяет приоритет yt-dlp над другими источниками названия."""

    async def fake_ytdlp(url: str) -> str | None:
        return "Заголовок из yt-dlp"

    async def fail_fetch(*args, **kwargs) -> None:
        raise AssertionError("Резервные источники не должны вызываться")

    monkeypatch.setattr(video_service, "fetch_ytdlp_title", fake_ytdlp)
    monkeypatch.setattr(video_service, "fetch_oembed_title", fail_fetch)
    monkeypatch.setattr(video_service, "fetch_video_page", fail_fetch)

    title = await video_service.resolve_video_title("https://youtube.com/shorts/abc", "youtube")

    assert title == "Заголовок из yt-dlp"


@pytest.mark.asyncio
async def test_resolve_video_title_falls_back_to_html(monkeypatch) -> None:
    """Проверяет fallback к HTML, если yt-dlp и oEmbed ничего не дали."""

    async def fake_none(*args, **kwargs) -> None:
        return None

    async def fake_html(url: str) -> str:
        return '<meta property="og:title" content="HTML заголовок | TikTok">'

    monkeypatch.setattr(video_service, "fetch_ytdlp_title", fake_none)
    monkeypatch.setattr(video_service, "fetch_oembed_title", fake_none)
    monkeypatch.setattr(video_service, "fetch_video_page", fake_html)

    title = await video_service.resolve_video_title("https://www.tiktok.com/@user/video/1", "tiktok")

    assert title == "HTML заголовок"


@pytest.mark.asyncio
async def test_resolve_video_title_quickly_returns_fallback_on_timeout(
    monkeypatch,
) -> None:
    """Проверяет быстрый fallback при таймауте получения названия."""

    async def fake_resolve(url: str, platform: str) -> str:
        await asyncio.sleep(0.01)
        return "Не должен успеть"

    monkeypatch.setattr(video_service, "resolve_video_title", fake_resolve)
    monkeypatch.setattr(video_service, "TITLE_RESOLUTION_TIMEOUT_SECONDS", 0.001)

    title = await video_service.resolve_video_title_quickly(
        "https://youtube.com/shorts/abc123",
        "youtube",
    )

    assert title == "youtube.com/shorts/abc123"


def test_is_fallback_title_detects_url_and_generated_title() -> None:
    """Проверяет распознавание fallback-названия вместо реального заголовка."""

    url = "https://youtube.com/shorts/abc123"
    fallback = video_service.build_video_title(url, "youtube")

    assert video_service.is_fallback_title(fallback, url, "youtube") is True
    assert video_service.is_fallback_title(url, url, "youtube") is True
    assert video_service.is_fallback_title("Настоящее название", url, "youtube") is False
