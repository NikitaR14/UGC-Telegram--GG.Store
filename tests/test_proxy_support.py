from __future__ import annotations

from bot.config import get_settings
from bot import main as bot_main


def test_build_bot_session_returns_none_without_proxy(monkeypatch) -> None:
    """Проверяет, что без настройки proxy создаётся обычная сессия."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.delenv("TELEGRAM_PROXY_URL", raising=False)
    get_settings.cache_clear()

    session = bot_main.build_bot_session()

    assert session is None
    get_settings.cache_clear()


def test_build_bot_session_uses_proxy_from_env(monkeypatch) -> None:
    """Проверяет создание Telegram-сессии с proxy."""

    captured: dict[str, str] = {}

    class FakeSession:
        def __init__(self, proxy: str) -> None:
            captured["proxy"] = proxy

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "  http://127.0.0.1:8080  ")
    get_settings.cache_clear()
    monkeypatch.setattr(bot_main, "AiohttpSession", FakeSession)

    session = bot_main.build_bot_session()

    assert isinstance(session, FakeSession)
    assert captured["proxy"] == "http://127.0.0.1:8080"
    get_settings.cache_clear()


def test_build_bot_session_falls_back_without_proxy_dependency(monkeypatch) -> None:
    """Проверяет, что бот не падает, если proxy-библиотека не установлена."""

    class BrokenSession:
        def __init__(self, proxy: str) -> None:
            raise RuntimeError("aiohttp-socks is not installed")

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "http://127.0.0.1:8080")
    get_settings.cache_clear()
    monkeypatch.setattr(bot_main, "AiohttpSession", BrokenSession)

    session = bot_main.build_bot_session()

    assert session is None
    get_settings.cache_clear()
