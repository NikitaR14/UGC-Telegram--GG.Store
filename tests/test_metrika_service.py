from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDictProxy, CIMultiDict

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

    params = metrika._build_event_params(
        user,
        metrika.MetrikaGoal.PAYOUT_SUM,
        extra_params={"video_id": 7, "payout_amount": 500.0},
    )

    assert params["telegram"]["user_id"] == 12345
    assert params["telegram"]["username"] == "@creator"
    assert params["telegram"]["phone"] is None
    assert params["finance"]["balance"] == 500.0
    assert params["finance"]["total_withdrawn"] == 1500.0
    assert params["bot"]["goal"] == "payout_sum"
    assert params["bot"]["time_in_bot_seconds"] >= 80
    assert params["extra"]["video_id"] == 7
    assert params["extra"]["payout_amount"] == 500.0


def test_build_virtual_page_url_uses_configured_base_url(monkeypatch) -> None:
    """Проверяет виртуальный URL для событий Метрики."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("YANDEX_METRIKA_BASE_URL", "https://t.me/test_bot/")
    get_settings.cache_clear()

    url = metrika._build_virtual_page_url(metrika.MetrikaGoal.DOWNLOAD_BANNER)

    assert url == "https://t.me/test_bot/download_banner"
    get_settings.cache_clear()


def test_build_event_hit_params_adds_goal_value_for_payout() -> None:
    """Проверяет передачу стоимости цели для суммы выплат."""

    payload = {
        "extra": {
            "video_id": 7,
            "payout_amount": 500.0,
        },
    }

    params = metrika._build_event_hit_params(
        counter_id="109115307",
        client_id="12345",
        goal=metrika.MetrikaGoal.PAYOUT_SUM,
        page_url="https://t.me/test_bot/payout_sum",
        payload=payload,
        secret_token="secret",
    )

    assert params["ea"] == "payout_sum"
    assert params["dr"] == metrika.METRIKA_REFERRER
    assert params["ev"] == "500.0"
    assert params["cu"] == "RUB"


def test_build_event_hit_params_skips_goal_value_for_regular_goal() -> None:
    """Проверяет, что обычные цели не получают стоимость выплаты."""

    params = metrika._build_event_hit_params(
        counter_id="109115307",
        client_id="12345",
        goal=metrika.MetrikaGoal.BOT_START,
        page_url="https://t.me/test_bot/bot_start",
        payload={},
        secret_token="secret",
    )

    assert params["ea"] == "bot_start"
    assert "ev" not in params
    assert "cu" not in params


def test_metrika_disabled_without_secret_token(monkeypatch) -> None:
    """Проверяет, что без secret token интеграция не активируется."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("YANDEX_METRIKA_COUNTER_ID", "109115307")
    monkeypatch.setenv("YANDEX_METRIKA_SECRET_TOKEN", "")
    get_settings.cache_clear()

    assert metrika.is_metrika_enabled() is False
    get_settings.cache_clear()


def test_metrika_enabled_strips_config_values(monkeypatch) -> None:
    """Проверяет защиту от пробелов при копировании настроек."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("YANDEX_METRIKA_COUNTER_ID", " 109115307 ")
    monkeypatch.setenv("YANDEX_METRIKA_SECRET_TOKEN", " token-with-spaces ")
    get_settings.cache_clear()

    assert metrika.is_metrika_enabled() is True
    assert metrika._normalize_optional(" token ") == "token"
    get_settings.cache_clear()


def test_format_safe_error_hides_request_url_and_secret() -> None:
    """Проверяет, что secret token не попадёт в лог ошибки."""

    request_info = RequestInfo(
        url="https://mc.yandex.ru/collect?ms=secret-token",
        method="POST",
        headers=CIMultiDictProxy(CIMultiDict()),
        real_url="https://mc.yandex.ru/collect?ms=secret-token",
    )
    error = ClientResponseError(
        request_info=request_info,
        history=(),
        status=400,
        message="Bad request",
    )

    safe_error = metrika._format_safe_error(error)

    assert safe_error == "HTTP 400: Bad request"
    assert "secret-token" not in safe_error
    assert "mc.yandex.ru" not in safe_error


def test_format_safe_error_includes_limited_response_text() -> None:
    """Проверяет безопасный текст ответа Метрики для диагностики."""

    error = metrika.MetrikaRequestError(
        status=400,
        response_text="invalid parameter" * 30,
    )

    safe_error = metrika._format_safe_error(error)

    assert safe_error.startswith("HTTP 400: invalid parameter")
    assert len(safe_error) <= len("HTTP 400: ") + metrika.METRIKA_ERROR_TEXT_LIMIT
