from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from bot.handlers.admin import moderation
from bot.handlers.admin.moderation import (
    ADMIN_TITLE_LENGTH,
    APPROVED_STATUS,
    PAYMENT_DETAILS_EMPTY_TEXT,
    PENDING_STATUS,
    REJECTED_STATUS,
    APPROVE_SUCCESS_TEXT,
    build_admin_all_videos_text,
    build_admin_detail_text,
    build_admin_list_items,
    build_admin_payment_details,
    build_approve_success_text,
    get_moderation_error_text,
    get_paid_error_text,
    has_payment_details,
    normalize_page,
    normalize_status,
    parse_action_context,
    parse_admin_list_callback,
    parse_admin_view_callback,
    parse_payout_amount,
    parse_status_from_menu,
    parse_video_id,
    shorten_admin_title,
)


def build_user(**overrides) -> SimpleNamespace:
    """Создаёт тестового пользователя для helper-тестов админки."""

    payload = {
        "user_id": 1001,
        "username": "moderated_user",
        "payment_method": "card",
        "payment_details": "5555444433332222",
        "is_admin_session": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def build_video(**overrides) -> SimpleNamespace:
    """Создаёт тестовую заявку для helper-функций админки."""

    payload = {
        "video_id": 15,
        "user_id": 1001,
        "url": "https://youtube.com/shorts/abc123",
        "platform": "youtube",
        "title": "Очень длинное тестовое название ролика для проверки",
        "status": PENDING_STATUS,
        "payout_amount": 1500.0,
        "views_count": 12345,
        "likes_count": 678,
        "comments_count": None,
        "shares_count": 42,
        "reject_reason": None,
        "created_at": datetime(2026, 5, 4, 12, 30, 0),
        "user": build_user(),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_parse_video_id_supports_old_and_new_callback_formats() -> None:
    """Проверяет извлечение номера заявки из разных callback-форматов."""

    assert parse_video_id("admin:approve:12") == 12
    assert parse_video_id("admin:paid:12:approved:2") == 12
    assert parse_video_id("admin:approve:not-a-number") is None


def test_parse_admin_callbacks_extract_context() -> None:
    """Проверяет разбор callback-данных для разделов и деталей админки."""

    assert parse_status_from_menu("admin:menu:pending") == PENDING_STATUS
    assert parse_status_from_menu("admin:menu:all") == "all"
    assert parse_status_from_menu("admin:menu:unknown") is None
    assert parse_admin_list_callback("admin:list:approved:3") == (APPROVED_STATUS, 3)
    assert parse_admin_view_callback("admin:view:rejected:2:44") == (REJECTED_STATUS, 2, 44)
    assert parse_action_context("admin:paid:44:approved:2") == (APPROVED_STATUS, 2)


def test_parse_payout_amount_validates_positive_number() -> None:
    """Проверяет валидацию суммы выплаты от администратора."""

    assert parse_payout_amount("250") == 250.0
    assert parse_payout_amount("1250,50") == 1250.5
    assert parse_payout_amount("0") is None
    assert parse_payout_amount("-15") is None
    assert parse_payout_amount("abc") is None


def test_normalize_helpers_validate_status_and_page() -> None:
    """Проверяет нормализацию статусов и страниц админки."""

    assert normalize_status(PENDING_STATUS) == PENDING_STATUS
    assert normalize_status("unknown") is None
    assert normalize_page(3) == 3
    assert normalize_page(0) == 1
    assert normalize_page("2") == 1


def test_shorten_admin_title_applies_limit() -> None:
    """Проверяет сокращение длинного названия в списке админки."""

    long_title = "x" * (ADMIN_TITLE_LENGTH + 10)
    short_title = shorten_admin_title(long_title)

    assert short_title.endswith("...")
    assert len(short_title) <= ADMIN_TITLE_LENGTH + 3


def test_payment_helpers_reflect_user_details_presence() -> None:
    """Проверяет определение наличия реквизитов у пользователя."""

    user_with_details = build_user()
    user_without_details = build_user(payment_method=None, payment_details=None)

    assert has_payment_details(user_with_details) is True
    assert has_payment_details(user_without_details) is False
    assert build_admin_payment_details(user_without_details) == PAYMENT_DETAILS_EMPTY_TEXT
    assert build_admin_payment_details(user_with_details) == "**** 2222"


def test_build_admin_list_items_adds_payment_marker_for_approved() -> None:
    """Проверяет индикатор реквизитов в списке одобренных заявок."""

    approved_video = build_video(status=APPROVED_STATUS)
    rejected_video = build_video(
        video_id=16,
        status=REJECTED_STATUS,
        user=build_user(payment_method=None, payment_details=None),
    )

    items = build_admin_list_items([approved_video, rejected_video])

    assert "рекв. есть" in items[0][1]
    assert "нет рекв." not in items[1][1]


def test_build_admin_detail_text_contains_payment_details_and_reason() -> None:
    """Проверяет содержимое детальной карточки заявки."""

    video = build_video(
        status=REJECTED_STATUS,
        reject_reason="Не соответствует требованиям",
    )

    text = build_admin_detail_text(video)

    assert "Банковская карта" in text
    assert "<code>**** 2222</code>" in text
    assert "5555444433332222" not in text
    assert "12 345" in text
    assert "678" in text
    assert "недоступно" in text
    assert "<blockquote>Не соответствует требованиям</blockquote>" in text


def test_build_admin_all_videos_text_includes_user_and_views() -> None:
    """Проверяет формат раздела со всеми видео пользователей."""

    text = build_admin_all_videos_text([build_video()])

    assert "Все видео" in text
    assert "@moderated_user" in text
    assert "12 345" in text


def test_build_approve_success_text_does_not_expose_payment_details() -> None:
    """Проверяет безопасный текст после одобрения ролика."""

    text = build_approve_success_text(build_video(), "@tester")

    assert text == APPROVE_SUCCESS_TEXT.format(
        video_id=15,
        username_label="@tester",
        payout_amount=1500,
    )
    assert "5555444433332222" not in text


def test_error_text_helpers_return_human_messages() -> None:
    """Проверяет преобразование технических ошибок в понятные тексты."""

    assert get_paid_error_text("has no payment details") == "У пользователя не привязаны реквизиты."
    assert get_paid_error_text("must be in status approved") == "Заявка уже не ждёт выплату."
    assert get_moderation_error_text("must be in status pending") == "Заявка уже обработана."
    assert get_moderation_error_text("not found") == "Заявка не найдена."
