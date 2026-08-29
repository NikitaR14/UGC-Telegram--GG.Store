from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.config import get_settings
from bot.services import video as video_service


def test_detect_platform_supports_tiktok_youtube_and_instagram_reels() -> None:
    """Проверяет распознавание поддерживаемых платформ по URL."""

    assert video_service.detect_platform("https://www.tiktok.com/@user/video/123") == "tiktok"
    assert video_service.detect_platform("https://youtube.com/shorts/abc123") == "youtube"
    assert video_service.detect_platform("https://youtu.be/abc123") == "youtube"
    assert video_service.detect_platform("https://www.instagram.com/reel/ABC123/") == "instagram"
    assert video_service.detect_platform("https://www.instagram.com/p/ABC123/") is None
    assert video_service.detect_platform("https://example.com/video") is None


def test_normalize_video_url_cleans_tiktok_tracking_tail() -> None:
    """Проверяет очистку TikTok-ссылки от query, fragment и текстового хвоста."""

    normalized = video_service.normalize_video_url(
        "https://www.tiktok.com/@user/video/7647872771137031457?is_from_webapp=1&sender_device=pc#frag #GGStoreUGCclips",
    )

    assert normalized == "https://www.tiktok.com/@user/video/7647872771137031457"


def test_normalize_video_url_cleans_instagram_reel_tracking_tail() -> None:
    """Проверяет очистку Reels-ссылки от query и fragment."""

    normalized = video_service.normalize_video_url(
        "https://www.instagram.com/reel/ABC123/?igsh=test#fragment",
    )

    assert normalized == "https://www.instagram.com/reel/ABC123"


def test_extract_ytdlp_metrics_reads_available_counters(monkeypatch) -> None:
    """Проверяет преобразование метрик yt-dlp."""

    class DummyYdl:
        def __init__(self, options) -> None:
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, int]:
            return {
                "view_count": 100_000,
                "like_count": 7_500,
                "comment_count": 320,
                "repost_count": 81,
            }

    monkeypatch.setattr(video_service, "YoutubeDL", DummyYdl)

    metrics = video_service.extract_ytdlp_metrics("https://instagram.com/reel/ABC123")

    assert metrics == video_service.VideoMetrics(100_000, 7_500, 320, 81)


def test_extract_instagram_metrics_uses_play_count(monkeypatch) -> None:
    """Проверяет использование публичного play_count для Reels."""

    class DummyLoader:
        def __init__(self, **kwargs) -> None:
            self.context = object()

    class DummyPost:
        video_play_count = 631_177
        video_view_count = None
        likes = 49_291
        comments = 94

    class DummyPostFactory:
        @staticmethod
        def from_shortcode(context, shortcode: str) -> DummyPost:
            assert shortcode == "Dclp2qwIqZ4"
            return DummyPost()

    monkeypatch.setattr(video_service, "Instaloader", DummyLoader)
    monkeypatch.setattr(video_service, "InstagramPost", DummyPostFactory)

    metrics = video_service.extract_instagram_metrics(
        "https://www.instagram.com/reel/Dclp2qwIqZ4/",
    )

    assert metrics == video_service.VideoMetrics(631_177, 49_291, 94)


@pytest.mark.asyncio
async def test_fetch_video_metrics_uses_instagram_fallback(monkeypatch) -> None:
    """Проверяет fallback после недоступного view_count в yt-dlp."""

    expected = video_service.VideoMetrics(631_177, 49_291, 94)

    async def fake_instagram_metrics(url: str) -> video_service.VideoMetrics:
        return expected

    monkeypatch.setattr(video_service, "YoutubeDL", None)
    monkeypatch.setattr(video_service, "fetch_instagram_metrics", fake_instagram_metrics)

    metrics = await video_service.fetch_video_metrics(
        "https://www.instagram.com/reel/Dclp2qwIqZ4/",
    )

    assert metrics == expected


@pytest.mark.asyncio
async def test_fetch_instagram_metrics_keeps_monitor_alive_on_error(monkeypatch) -> None:
    """Проверяет безопасный результат при временной ошибке Instagram."""

    async def fake_to_thread(*args, **kwargs) -> None:
        raise video_service.InstaloaderException("temporarily blocked")

    monkeypatch.setattr(video_service.asyncio, "to_thread", fake_to_thread)

    metrics = await video_service.fetch_instagram_metrics(
        "https://www.instagram.com/reel/Dclp2qwIqZ4/",
    )

    assert metrics is None


def test_normalize_video_url_keeps_short_youtube_query() -> None:
    """Проверяет сохранение query у коротких YouTube-ссылок."""

    normalized = video_service.normalize_video_url(
        "https://youtu.be/abc123?si=test123 #GGStoreUGCclips",
    )

    assert normalized == "https://youtu.be/abc123?si=test123"


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


def test_extract_tiktok_views_from_html_reads_play_count() -> None:
    """Проверяет извлечение просмотров TikTok из HTML fallback."""

    html = """
    <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
      {"__DEFAULT_SCOPE__":{"webapp.video-detail":{"itemInfo":{"itemStruct":{"stats":{"playCount":"123456"}}}}}}
    </script>
    """

    assert video_service.extract_tiktok_views_from_html(html) == 123456


def test_should_retry_tiktok_page_with_curl_detects_protective_html() -> None:
    """Проверяет распознавание защитной короткой TikTok-страницы."""

    assert video_service.should_retry_tiktok_page_with_curl("<html>blocked</html>") is True
    assert video_service.should_retry_tiktok_page_with_curl('{"stats":{"playCount":"1"}}') is False


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


def test_build_ytdlp_options_adds_proxy_from_env(monkeypatch) -> None:
    """Проверяет проброс proxy в yt-dlp при наличии настройки."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("VIDEO_PROXY_URL", "  http://127.0.0.1:8080  ")
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options()

    assert options["proxy"] == "http://127.0.0.1:8080"
    get_settings.cache_clear()


def test_build_ytdlp_options_adds_cookiefile_when_file_exists(
    monkeypatch,
    tmp_path,
) -> None:
    """Проверяет проброс cookies-файла в yt-dlp при наличии файла."""

    cookies_file = tmp_path / "tiktok-cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("VIDEO_COOKIES_FILE", str(cookies_file))
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options()

    assert options["cookiefile"] == str(cookies_file)
    get_settings.cache_clear()


def test_build_ytdlp_options_ignores_missing_cookiefile(monkeypatch) -> None:
    """Проверяет игнорирование несуществующего cookies-файла."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("VIDEO_COOKIES_FILE", "/tmp/definitely-missing-cookies.txt")
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options()

    assert "cookiefile" not in options
    get_settings.cache_clear()


def test_build_ytdlp_options_adds_impersonation_for_tiktok_from_env(monkeypatch) -> None:
    """Проверяет явный проброс impersonation-цели для TikTok."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("VIDEO_IMPERSONATE_TARGET", "chrome124")
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options("tiktok")

    assert options["impersonate"] == "chrome124"
    get_settings.cache_clear()


def test_build_ytdlp_options_adds_default_impersonation_for_tiktok(
    monkeypatch,
) -> None:
    """Проверяет дефолтный impersonation для TikTok при доступном curl-cffi."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.delenv("VIDEO_IMPERSONATE_TARGET", raising=False)
    monkeypatch.setattr(video_service, "find_spec", lambda name: object())
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options("tiktok")

    assert options["impersonate"] == "chrome"
    get_settings.cache_clear()


def test_build_ytdlp_options_skips_default_impersonation_without_curl_cffi(
    monkeypatch,
) -> None:
    """Проверяет, что без curl-cffi дефолтный impersonation не включается."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.delenv("VIDEO_IMPERSONATE_TARGET", raising=False)
    monkeypatch.setattr(video_service, "find_spec", lambda name: None)
    get_settings.cache_clear()

    options = video_service.build_ytdlp_options("tiktok")

    assert "impersonate" not in options
    get_settings.cache_clear()


def test_is_expected_video_views_error_detects_known_noisy_cases() -> None:
    """Проверяет распознавание ожидаемых ошибок недоступных видео."""

    assert video_service.is_expected_video_views_error("ERROR: Unsupported URL: https://...")
    assert video_service.is_expected_video_views_error("ERROR: [youtube] id: Video unavailable")
    assert video_service.is_expected_video_views_error(
        "ERROR: This user's account is likely either private or all of their videos are private",
    )
    assert video_service.is_expected_video_views_error("Some brand new unknown error") is False


def test_is_expected_video_title_error_detects_known_noisy_cases() -> None:
    """Проверяет распознавание ожидаемых ошибок получения названия."""

    assert video_service.is_expected_video_title_error("ERROR: Your IP address is blocked")
    assert video_service.is_expected_video_title_error(
        "ERROR: Unexpected response from webpage request",
    )
    assert video_service.is_expected_video_title_error("Unexpected brand new title error") is False


@pytest.mark.asyncio
async def test_fetch_oembed_title_passes_proxy_to_request(monkeypatch) -> None:
    """Проверяет проброс proxy в HTTP-запрос oEmbed."""

    captured_kwargs: dict[str, object] = {}

    class FakeResponse:
        status = 200

        async def json(self, content_type=None) -> dict[str, str]:
            return {"title": "Тестовый ролик"}

    class FakeResponseContext:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, **kwargs) -> FakeResponseContext:
            captured_kwargs.update(kwargs)
            return FakeResponseContext()

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("VIDEO_PROXY_URL", "socks5://127.0.0.1:1080")
    get_settings.cache_clear()
    monkeypatch.setattr(video_service, "ClientSession", FakeSession)

    title = await video_service.fetch_oembed_title(
        "https://youtube.com/shorts/abc123",
        "youtube",
    )

    assert title == "Тестовый ролик"
    assert captured_kwargs["proxy"] == "socks5://127.0.0.1:1080"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fetch_video_views_uses_tiktok_html_fallback(monkeypatch) -> None:
    """Проверяет fallback к HTML, если yt-dlp не смог получить просмотры TikTok."""

    async def fake_html(url: str) -> str:
        return '{"stats":{"playCount":"987654"}}'

    monkeypatch.setattr(video_service, "YoutubeDL", object())
    monkeypatch.setattr(video_service, "extract_ytdlp_views", lambda url: None)
    monkeypatch.setattr(video_service, "fetch_video_page", fake_html)

    views = await video_service.fetch_video_views(
        "https://www.tiktok.com/@user/video/7647872771137031457?is_from_webapp=1",
    )

    assert views == 987654


@pytest.mark.asyncio
async def test_fetch_video_page_uses_curl_fallback_for_tiktok_short_html(
    monkeypatch,
) -> None:
    """Проверяет fallback на `curl` для короткой TikTok-страницы без данных."""

    class FakeResponse:
        status = 200

        async def text(self) -> str:
            return "<html>blocked</html>"

    class FakeResponseContext:
        async def __aenter__(self) -> FakeResponse:
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, **kwargs) -> FakeResponseContext:
            return FakeResponseContext()

    async def fake_curl(url: str) -> str:
        return '{"stats":{"playCount":"123"}}'

    monkeypatch.setattr(video_service, "ClientSession", FakeSession)
    monkeypatch.setattr(video_service, "fetch_tiktok_page_via_curl", fake_curl)

    html = await video_service.fetch_video_page(
        "https://www.tiktok.com/@user/video/7647872771137031457",
    )

    assert html == '{"stats":{"playCount":"123"}}'


def test_run_curl_for_html_uses_simple_shell_compatible_command(monkeypatch) -> None:
    """Проверяет, что TikTok curl-fallback не подменяет UA и близок к ручному curl."""

    captured_command: list[str] = []

    def fake_run(*args, **kwargs):
        nonlocal captured_command
        captured_command = list(args[0])
        return SimpleNamespace(stdout='{"stats":{"playCount":"321"}}')

    monkeypatch.setattr(video_service.subprocess, "run", fake_run)

    html = video_service.run_curl_for_html(
        "https://www.tiktok.com/@user/video/7647872771137031457",
    )

    assert html == '{"stats":{"playCount":"321"}}'
    assert captured_command[:2] == ["curl", "-L"]
    assert "-A" not in captured_command
