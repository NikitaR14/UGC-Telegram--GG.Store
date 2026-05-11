from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.config import get_settings
from bot.db.models import User
from bot.services import metrika


def test_build_event_params_contains_safe_user_data() -> None:
    """Проверяет параметры события без передачи лишних персональных данных."""

    user = User(
        user_id=12345,
        username="creator",
        balance=500.0,
        total_withdrawn=1500.0,
        created_at=datetime.now(UTC) - timedelta(seconds=90),
    )

    params = metrika._build_event_params(user, metrika.MetrikaGoal.BOT_START)

    assert params["telegram"]["user_id"] == 12345
    assert params["telegram"]["username"] == "@creator"
    assert params["telegram"]["phone"] is None
    assert params["finance"]["balance"] == 500.0
    assert params["finance"]["total_withdrawn"] == 1500.0
    assert params["bot"]["goal"] == "bot_start"
    assert params["bot"]["time_in_bot_seconds"] >= 80


def test_build_virtual_page_url_uses_configured_base_url(monkeypatch) -> None:
    """Проверяет виртуальный URL для событий Метрики."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("YANDEX_METRIKA_BASE_URL", "https://t.me/test_bot/")
    get_settings.cache_clear()

    url = metrika._build_virtual_page_url(metrika.MetrikaGoal.DOWNLOAD_BANNER)

    assert url == "https://t.me/test_bot/download_banner"
    get_settings.cache_clear()


def test_metrika_disabled_without_secret_token(monkeypatch) -> None:
    """Проверяет, что без secret token интеграция не активируется."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("YANDEX_METRIKA_COUNTER_ID", "109115307")
    monkeypatch.setenv("YANDEX_METRIKA_SECRET_TOKEN", "")
    get_settings.cache_clear()

    assert metrika.is_metrika_enabled() is False
    get_settings.cache_clear()
