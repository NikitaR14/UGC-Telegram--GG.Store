from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import aiohttp
from aiohttp import ClientResponseError
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.config import get_settings
from bot.db.models import User

METRIKA_COLLECT_URL = "https://mc.yandex.ru/collect"
METRIKA_TIMEOUT_SECONDS = 3
METRIKA_REFERRER = "https://t.me/"
METRIKA_ERROR_TEXT_LIMIT = 200
METRIKA_CURRENCY = "RUB"


class MetrikaGoal(StrEnum):
    """Идентификаторы целей в Яндекс Метрике."""

    BOT_START = "bot_start"
    ADD_VIDEO = "add_video"
    DOWNLOAD_BANNER = "download_banner"
    TIME_IN_BOT = "time_in_bot"
    PAYOUT_SUM = "payout_sum"


def is_metrika_enabled() -> bool:
    """Проверяет, достаточно ли настроек для отправки событий."""

    settings = get_settings()
    return bool(
        _normalize_optional(settings.yandex_metrika_counter_id)
        and _normalize_optional(settings.yandex_metrika_secret_token)
    )


async def track_metrika_goal(
    user: User,
    goal: MetrikaGoal,
    *,
    extra_params: dict[str, Any] | None = None,
) -> None:
    """Отправляет виртуальный визит и достижение цели в Яндекс Метрику."""

    if not is_metrika_enabled():
        logger.info("Yandex Metrika tracking skipped | goal={} reason=disabled", goal.value)
        return

    settings = get_settings()
    counter_id = _normalize_optional(settings.yandex_metrika_counter_id)
    secret_token = _normalize_optional(settings.yandex_metrika_secret_token)
    if not counter_id or not secret_token:
        return

    page_url = _build_virtual_page_url(goal)
    payload = _build_event_params(user, goal, extra_params=extra_params)
    try:
        event_params = _build_event_hit_params(
            counter_id=counter_id,
            client_id=str(user.user_id),
            goal=goal,
            page_url=page_url,
            payload=payload,
            secret_token=secret_token,
        )
        pageview_status = await _send_metrika_hit(
            {
                "tid": counter_id,
                "cid": str(user.user_id),
                "t": "pageview",
                "dr": METRIKA_REFERRER,
                "dl": page_url,
                "dt": f"Telegram bot: {goal.value}",
                "ms": secret_token,
            },
        )
        event_status = await _send_metrika_hit(event_params)
        logger.info(
            "Yandex Metrika tracking sent | goal={} user={} pageview_status={} event_status={}",
            goal.value,
            user.user_id,
            pageview_status,
            event_status,
        )
    except (aiohttp.ClientError, TimeoutError) as error:
        logger.warning(
            "Yandex Metrika tracking failed | goal={} user={} error={}",
            goal.value,
            user.user_id,
            _format_safe_error(error),
        )


def _build_event_params(
    user: User,
    goal: MetrikaGoal,
    *,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собирает безопасные параметры события для аналитики."""

    params: dict[str, Any] = {
        "telegram": {
            "user_id": user.user_id,
            "username": _format_username(user.username),
            "phone": None,
        },
        "finance": {
            "balance": float(user.balance or 0),
            "total_withdrawn": float(user.total_withdrawn or 0),
        },
        "bot": {
            "goal": goal.value,
            "time_in_bot_seconds": _get_time_in_bot_seconds(user),
        },
    }
    if extra_params:
        params["extra"] = extra_params
    return params


def _build_event_hit_params(
    *,
    counter_id: str,
    client_id: str,
    goal: MetrikaGoal,
    page_url: str,
    payload: dict[str, Any],
    secret_token: str,
) -> dict[str, str]:
    """Собирает параметры event-хита для Measurement Protocol."""

    params = {
        "tid": counter_id,
        "cid": client_id,
        "t": "event",
        "dr": METRIKA_REFERRER,
        "dl": page_url,
        "ea": goal.value,
        "params": json.dumps(payload, ensure_ascii=False),
        "ms": secret_token,
    }
    goal_value = _extract_goal_value(goal, payload)
    if goal_value is not None:
        params["ev"] = str(goal_value)
        params["cu"] = METRIKA_CURRENCY
    return params


def _extract_goal_value(goal: MetrikaGoal, payload: dict[str, Any]) -> float | None:
    """Возвращает стоимость цели для Метрики, если она применима."""

    if goal != MetrikaGoal.PAYOUT_SUM:
        return None
    extra = payload.get("extra")
    if not isinstance(extra, dict):
        return None
    payout_amount = extra.get("payout_amount")
    if not isinstance(payout_amount, int | float):
        return None
    if payout_amount <= 0:
        return None
    return float(payout_amount)


def _build_virtual_page_url(goal: MetrikaGoal) -> str:
    """Возвращает виртуальный URL экрана бота для Метрики."""

    settings = get_settings()
    base_url = settings.yandex_metrika_base_url.strip().rstrip("/")
    return f"{base_url}/{goal.value}"


def _normalize_optional(value: str | None) -> str | None:
    """Убирает случайные пробелы из значения настройки."""

    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _format_username(username: str | None) -> str | None:
    """Форматирует Telegram username как тег пользователя."""

    if not username:
        return None
    return username if username.startswith("@") else f"@{username}"


def _get_time_in_bot_seconds(user: User) -> int:
    """Считает примерное время с первого появления пользователя в боте."""

    created_at = user.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - created_at).total_seconds()))


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(min=1, max=3),
    retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
    reraise=True,
)
async def _send_metrika_hit(params: dict[str, str | None]) -> int:
    """Отправляет один hit в Measurement Protocol Метрики."""

    timeout = aiohttp.ClientTimeout(total=METRIKA_TIMEOUT_SECONDS)
    clean_params = {key: value for key, value in params.items() if value is not None}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(METRIKA_COLLECT_URL, params=clean_params) as response:
            if response.status >= 400:
                response_text = await response.text()
                raise MetrikaRequestError(response.status, response_text)
            return response.status


class MetrikaRequestError(aiohttp.ClientError):
    """Ошибка ответа Measurement Protocol без чувствительных данных."""

    def __init__(self, status: int, response_text: str) -> None:
        self.status = status
        self.response_text = response_text[:METRIKA_ERROR_TEXT_LIMIT]
        super().__init__(f"HTTP {status}: {self.response_text}")


def _format_safe_error(error: BaseException) -> str:
    """Форматирует ошибку без URL и secret token."""

    if isinstance(error, MetrikaRequestError):
        return f"HTTP {error.status}: {error.response_text}"
    if isinstance(error, ClientResponseError):
        return f"HTTP {error.status}: {error.message}"
    return error.__class__.__name__
