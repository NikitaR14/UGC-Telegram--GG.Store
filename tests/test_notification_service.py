from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

from bot.services import notification as notification_service
from bot.ui.emojis import CARD_TEXT, STAR_TEXT, USDT_TEXT


class DummyBot:
    """Тестовый бот с накапливанием отправленных сообщений."""

    def __init__(self, side_effect: Exception | None = None) -> None:
        self.side_effect = side_effect
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs) -> None:
        if self.side_effect is not None:
            raise self.side_effect
        self.messages.append(kwargs)


def build_user(**overrides) -> SimpleNamespace:
    """Создаёт тестового пользователя для уведомлений."""

    payload = {
        "user_id": 1001,
        "username": "tester",
        "payment_method": "card",
        "payment_details": "5555444433332222",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def build_video(**overrides) -> SimpleNamespace:
    """Создаёт тестовую заявку для уведомлений."""

    payload = {
        "video_id": 12,
        "user_id": 1001,
        "url": "https://youtube.com/shorts/abc123",
        "title": "Тестовый ролик",
        "payout_amount": 1500.0,
        "reject_reason": "Не подошёл баннер",
        "created_at": datetime(2026, 5, 4, 12, 0, 0),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_format_payment_method_returns_human_labels() -> None:
    """Проверяет человекочитаемые подписи способов вывода."""

    assert notification_service.format_payment_method("card") == f"{CARD_TEXT} Банковская карта"
    assert notification_service.format_payment_method("usdt") == f"{USDT_TEXT} USDT TRC-20"
    assert notification_service.format_payment_method("ggstore") == f"{STAR_TEXT} Баланс gg.store"
    assert notification_service.format_payment_method(None) == "Не указан"


def test_build_applications_line_formats_one_and_many_ids() -> None:
    """Проверяет форматирование номеров заявок в админском уведомлении."""

    assert notification_service.build_applications_line([]) == "<b>Заявки:</b> не найдены"
    assert notification_service.build_applications_line([12]) == "<b>Заявка:</b> #00012"
    assert notification_service.build_applications_line([12, 15]) == "<b>Заявки:</b> #00012, #00015"


@pytest.mark.asyncio
async def test_notify_video_approved_with_payment_details_sends_masked_account() -> None:
    """Проверяет текст одобрения при наличии реквизитов пользователя."""

    bot = DummyBot()
    user = build_user()
    video = build_video()

    await notification_service.notify_video_approved(bot, user, video)

    assert len(bot.messages) == 1
    text = str(bot.messages[0]["text"])
    assert "Тестовый ролик" in text
    assert "1500 ₽" in text
    assert "**** 2222" in text


@pytest.mark.asyncio
async def test_notify_video_approved_without_payment_details_requests_balance_setup() -> None:
    """Проверяет текст одобрения без привязанных реквизитов."""

    bot = DummyBot()
    user = build_user(payment_details=None, payment_method=None)
    video = build_video()

    await notification_service.notify_video_approved(bot, user, video)

    text = str(bot.messages[0]["text"])
    assert "Привяжите пожалуйста платёжные реквизиты" in text


@pytest.mark.asyncio
async def test_notify_video_rejected_includes_reason_blockquote() -> None:
    """Проверяет текст уведомления об отклонении заявки."""

    bot = DummyBot()
    user = build_user()
    video = build_video(reject_reason="Причина модерации")

    await notification_service.notify_video_rejected(bot, user, video)

    text = str(bot.messages[0]["text"])
    assert "<blockquote>Причина модерации</blockquote>" in text


@pytest.mark.asyncio
async def test_notify_video_paid_mentions_amount() -> None:
    """Проверяет текст уведомления о подтверждённой выплате."""

    bot = DummyBot()
    user = build_user()
    video = build_video()

    await notification_service.notify_video_paid(bot, user, video)

    text = str(bot.messages[0]["text"])
    assert "Выплата отправлена" in text
    assert "1500 ₽" in text


@pytest.mark.asyncio
async def test_notify_admins_about_payment_details_sends_to_all_admins(
    monkeypatch,
) -> None:
    """Проверяет отправку уведомления о реквизитах всем администраторам."""

    bot = DummyBot()
    user = build_user(payment_details="TRC20_TEST_WALLET")

    class DummyRepository:
        async def get_active_admin_ids(self) -> list[int]:
            return [111, 222]

    monkeypatch.setattr(notification_service, "BotRepository", lambda _: DummyRepository())
    monkeypatch.setattr(notification_service, "get_session_factory", lambda: None)

    await notification_service.notify_admins_about_payment_details(bot, user, [12, 14])

    assert [message["chat_id"] for message in bot.messages] == [111, 222]
    assert "<b>Раздел:</b> Одобренные" in str(bot.messages[0]["text"])
    assert "#00012, #00014" in str(bot.messages[0]["text"])


@pytest.mark.asyncio
async def test_safe_notify_swallows_forbidden_and_bad_request() -> None:
    """Проверяет, что постоянные Telegram-ошибки не пробрасываются наружу."""

    forbidden_bot = DummyBot(side_effect=TelegramForbiddenError(method="sendMessage", message="blocked"))
    bad_request_bot = DummyBot(side_effect=TelegramBadRequest(method="sendMessage", message="bad"))

    await notification_service._safe_notify(forbidden_bot, 1, "text", "approved")
    await notification_service._safe_notify(bad_request_bot, 1, "text", "approved")


@pytest.mark.asyncio
async def test_safe_notify_admin_swallows_network_error_after_retries() -> None:
    """Проверяет безопасную обработку сетевой ошибки в админском уведомлении."""

    network_bot = DummyBot(side_effect=TelegramNetworkError(method="sendMessage", message="timeout"))

    await notification_service._safe_notify_admin(
        network_bot,
        admin_id=1,
        text="text",
        operation="payment_details",
    )
