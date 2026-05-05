from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from bot.handlers.admin import auth as admin_auth


@dataclass
class DummyState:
    """Минимальная реализация state для тестов admin-flow."""

    current_state: object | None = None
    cleared: bool = False

    async def set_state(self, value: object) -> None:
        self.current_state = value

    async def clear(self) -> None:
        self.current_state = None
        self.cleared = True


@dataclass
class DummyMessage:
    """Минимальная реализация aiogram Message для handler-тестов."""

    from_user: SimpleNamespace | None
    text: str | None = None
    answers: list[dict[str, object]] = field(default_factory=list)

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        self.answers.append({"text": text, "reply_markup": reply_markup})


def build_user(user_id: int, username: str = "tester") -> SimpleNamespace:
    """Создаёт тестового пользователя Telegram."""

    return SimpleNamespace(id=user_id, username=username)


@pytest.mark.asyncio
async def test_enter_admin_mode_requests_password_for_any_user(
    repository,
    session_factory,
    monkeypatch,
) -> None:
    """Проверяет, что /admin доступен любому пользователю до ввода пароля."""

    monkeypatch.setattr(admin_auth, "get_session_factory", lambda: session_factory)
    message = DummyMessage(from_user=build_user(10))
    state = DummyState()

    await admin_auth.enter_admin_mode(message, state)

    assert state.current_state == admin_auth.AdminAuthState.waiting_for_password
    assert message.answers == [{"text": admin_auth.ADMIN_PROMPT_TEXT, "reply_markup": None}]


@pytest.mark.asyncio
async def test_enter_admin_mode_requests_password_for_admin_without_session(
    repository,
    session_factory,
    monkeypatch,
) -> None:
    """Проверяет вход админа без активной admin-сессии."""

    monkeypatch.setattr(admin_auth, "get_session_factory", lambda: session_factory)
    message = DummyMessage(from_user=build_user(42))
    state = DummyState()

    await admin_auth.enter_admin_mode(message, state)

    assert state.current_state == admin_auth.AdminAuthState.waiting_for_password
    assert message.answers == [{"text": admin_auth.ADMIN_PROMPT_TEXT, "reply_markup": None}]


@pytest.mark.asyncio
async def test_enter_admin_mode_opens_dashboard_for_existing_session(
    repository,
    session_factory,
    monkeypatch,
) -> None:
    """Проверяет повторный вход админа с уже активной сессией."""

    monkeypatch.setattr(admin_auth, "get_session_factory", lambda: session_factory)
    await repository.upsert_user(42, "admin")
    await repository.set_admin_session(42, True)
    message = DummyMessage(from_user=build_user(42, "admin"))
    state = DummyState(current_state=admin_auth.AdminAuthState.waiting_for_password)

    await admin_auth.enter_admin_mode(message, state)

    assert state.current_state is None
    assert state.cleared is True
    assert message.answers[0]["text"] == admin_auth.ADMIN_DASHBOARD_TEXT
    assert message.answers[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_handle_admin_password_rejects_wrong_password(
    repository,
    session_factory,
    monkeypatch,
) -> None:
    """Проверяет обработку неверного пароля администратора."""

    monkeypatch.setattr(admin_auth, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        admin_auth,
        "get_settings",
        lambda: SimpleNamespace(admin_password="secret"),
    )
    message = DummyMessage(from_user=build_user(42), text="wrong")
    state = DummyState(current_state=admin_auth.AdminAuthState.waiting_for_password)

    await admin_auth.handle_admin_password(message, state)

    user = await repository.get_user(42)
    assert message.answers == [{"text": admin_auth.WRONG_PASSWORD_TEXT, "reply_markup": None}]
    assert state.current_state == admin_auth.AdminAuthState.waiting_for_password
    assert user is None


@pytest.mark.asyncio
async def test_handle_admin_password_enables_session_on_success(
    repository,
    session_factory,
    monkeypatch,
) -> None:
    """Проверяет успешный вход администратора по паролю."""

    monkeypatch.setattr(admin_auth, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        admin_auth,
        "get_settings",
        lambda: SimpleNamespace(admin_password="secret"),
    )
    message = DummyMessage(from_user=build_user(42), text="secret")
    state = DummyState(current_state=admin_auth.AdminAuthState.waiting_for_password)

    await admin_auth.handle_admin_password(message, state)

    user = await repository.get_user(42)
    assert state.current_state is None
    assert state.cleared is True
    assert user is not None
    assert user.is_admin_session is True
    assert message.answers[0]["text"] == admin_auth.ADMIN_DASHBOARD_TEXT
    assert message.answers[0]["reply_markup"] is not None
