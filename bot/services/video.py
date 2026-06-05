from __future__ import annotations

import asyncio
import re
from html import unescape
from urllib.parse import urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout
from loguru import logger

from bot.config import get_settings

try:
    from yt_dlp import YoutubeDL
except ModuleNotFoundError:
    YoutubeDL = None

TIKTOK_HOST_PART = "tiktok.com"
YOUTUBE_HOST_PART = "youtube.com"
SHORTS_PATH_PART = "/shorts/"
YOUTU_BE_HOST = "youtu.be"
TITLE_PREVIEW_LENGTH = 40
TITLE_DISPLAY_LENGTH = 20
TITLE_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)'),
    re.compile(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)'),
    re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL),
)
TITLE_CLEANUP_SUFFIXES = (
    " - YouTube",
    " | TikTok",
    " | TikTok Lite",
)
REQUEST_TIMEOUT_SECONDS = 10
TITLE_RESOLUTION_TIMEOUT_SECONDS = 2.5
VIEWS_RESOLUTION_TIMEOUT_SECONDS = 6
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"
TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"


def _normalize_optional(value: str | None) -> str | None:
    """Очищает опциональное строковое значение от лишних пробелов."""

    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def get_video_proxy_url() -> str | None:
    """Возвращает proxy для внешних видеосервисов, если он настроен."""

    return _normalize_optional(get_settings().video_proxy_url)


def build_ytdlp_options() -> dict[str, object]:
    """Собирает базовые опции yt-dlp с опциональным proxy."""

    options: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": REQUEST_TIMEOUT_SECONDS,
    }
    proxy_url = get_video_proxy_url()
    if proxy_url:
        options["proxy"] = proxy_url
    return options


def detect_platform(url: str) -> str | None:
    """Определяет поддерживаемую платформу по ссылке."""

    normalized_url = url.strip()
    parsed_url = urlparse(normalized_url)
    hostname = (parsed_url.netloc or "").lower()
    path = parsed_url.path.lower()

    if TIKTOK_HOST_PART in hostname:
        return "tiktok"
    if YOUTUBE_HOST_PART in hostname and SHORTS_PATH_PART in path:
        return "youtube"
    if YOUTU_BE_HOST == hostname:
        return "youtube"
    return None


def build_video_title(url: str, platform: str) -> str:
    """Строит безопасный заголовок для отображения в истории."""

    parsed_url = urlparse(url.strip())
    hostname = parsed_url.netloc or platform
    path = parsed_url.path.strip("/")
    preview = path[:TITLE_PREVIEW_LENGTH]
    if len(path) > TITLE_PREVIEW_LENGTH:
        preview = f"{preview}..."
    if not preview:
        return hostname
    return f"{hostname}/{preview}"


def shorten_video_title(value: str, limit: int = TITLE_DISPLAY_LENGTH) -> str:
    """Ограничивает длину названия для компактного отображения."""

    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


async def resolve_video_title(url: str, platform: str) -> str:
    """Пытается получить реальное название видео, иначе возвращает fallback."""

    ytdlp_title = await fetch_ytdlp_title(url)
    if ytdlp_title:
        return ytdlp_title

    oembed_title = await fetch_oembed_title(url, platform)
    if oembed_title:
        return oembed_title

    html = await fetch_video_page(url)
    if not html:
        return build_video_title(url, platform)

    title = extract_title_from_html(html)
    if not title:
        return build_video_title(url, platform)
    return title


async def resolve_video_title_quickly(url: str, platform: str) -> str:
    """Быстро пытается получить название, не задерживая сценарий пользователя."""

    try:
        return await asyncio.wait_for(
            resolve_video_title(url, platform),
            timeout=TITLE_RESOLUTION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Video title resolution timed out | url={} platform={}", url, platform)
        return build_video_title(url, platform)


async def fetch_ytdlp_title(url: str) -> str | None:
    """Пытается получить название ролика через yt-dlp."""

    if YoutubeDL is None:
        return None

    try:
        return await asyncio.to_thread(extract_ytdlp_title, url)
    except Exception as error:
        logger.warning("yt-dlp title extraction failed | url={} error={}", url, str(error))
        return None


async def fetch_video_views(url: str) -> int | None:
    """Пытается получить число просмотров ролика."""

    if YoutubeDL is None:
        return None

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(extract_ytdlp_views, url),
            timeout=VIEWS_RESOLUTION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Video views resolution timed out | url={}", url)
        return None
    except Exception as error:
        logger.warning("Video views extraction failed | url={} error={}", url, str(error))
        return None


def extract_ytdlp_title(url: str) -> str | None:
    """Синхронно извлекает название ролика через yt-dlp."""

    if YoutubeDL is None:
        return None

    options = build_ytdlp_options()
    with YoutubeDL(options) as ydl:
        payload = ydl.extract_info(url, download=False)
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    if not isinstance(title, str):
        return None
    return normalize_title(title)


def extract_ytdlp_views(url: str) -> int | None:
    """Синхронно извлекает число просмотров ролика через yt-dlp."""

    if YoutubeDL is None:
        return None

    options = build_ytdlp_options()
    with YoutubeDL(options) as ydl:
        payload = ydl.extract_info(url, download=False)
    if not isinstance(payload, dict):
        return None
    view_count = payload.get("view_count")
    if not isinstance(view_count, int):
        return None
    return max(view_count, 0)


async def fetch_oembed_title(url: str, platform: str) -> str | None:
    """Пытается получить название ролика через oEmbed платформы."""

    oembed_url = get_oembed_url(platform)
    if not oembed_url:
        return None

    timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    params = {"url": url, "format": "json"}
    proxy_url = get_video_proxy_url()
    request_kwargs = {
        "params": params,
        "allow_redirects": True,
    }
    if proxy_url:
        request_kwargs["proxy"] = proxy_url

    try:
        async with ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(oembed_url, **request_kwargs) as response:
                if response.status >= 400:
                    logger.warning(
                        "oEmbed request failed | platform={} url={} status={}",
                        platform,
                        url,
                        response.status,
                    )
                    return None
                payload = await response.json(content_type=None)
    except ClientError as error:
        logger.warning(
            "oEmbed request failed | platform={} url={} error={}",
            platform,
            url,
            str(error),
        )
        return None
    except TimeoutError as error:
        logger.warning(
            "oEmbed timeout | platform={} url={} error={}",
            platform,
            url,
            str(error),
        )
        return None
    except ValueError as error:
        logger.warning(
            "oEmbed parse failed | platform={} url={} error={}",
            platform,
            url,
            str(error),
        )
        return None

    title = payload.get("title")
    if not isinstance(title, str):
        return None
    return normalize_title(title)


async def fetch_video_page(url: str) -> str | None:
    """Загружает HTML страницы видео."""

    timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    proxy_url = get_video_proxy_url()
    request_kwargs = {"allow_redirects": True}
    if proxy_url:
        request_kwargs["proxy"] = proxy_url
    try:
        async with ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, **request_kwargs) as response:
                if response.status >= 400:
                    logger.warning(
                        "Video page request failed | url={} status={}",
                        url,
                        response.status,
                    )
                    return None
                return await response.text()
    except ClientError as error:
        logger.warning("Video page request failed | url={} error={}", url, str(error))
        return None
    except TimeoutError as error:
        logger.warning("Video page timeout | url={} error={}", url, str(error))
        return None


def extract_title_from_html(html: str) -> str | None:
    """Извлекает заголовок видео из HTML."""

    for pattern in TITLE_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        title = normalize_title(match.group(1))
        if title:
            return title
    return None


def get_oembed_url(platform: str) -> str | None:
    """Возвращает endpoint oEmbed для платформы."""

    if platform == "youtube":
        return YOUTUBE_OEMBED_URL
    if platform == "tiktok":
        return TIKTOK_OEMBED_URL
    return None


def normalize_title(value: str) -> str | None:
    """Очищает заголовок от HTML-сущностей и хвостов платформ."""

    title = unescape(re.sub(r"\s+", " ", value)).strip()
    if not title:
        return None
    for suffix in TITLE_CLEANUP_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title or None


def is_fallback_title(title: str | None, url: str, platform: str) -> bool:
    """Проверяет, что вместо названия сохранён fallback из URL."""

    if not title:
        return True
    normalized_title = title.strip()
    normalized_url = url.strip()
    fallback_title = build_video_title(url, platform)
    return (
        normalized_title == fallback_title
        or normalized_title == normalized_url
        or normalized_title in normalized_url
    )
