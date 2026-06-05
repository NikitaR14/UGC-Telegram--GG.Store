from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.handlers.user import balance


@pytest.mark.asyncio
async def test_build_balance_text_does_not_include_uploaded_videos_count(
    monkeypatch,
) -> None:
    """Проверяет, что счётчик видео больше не отображается в балансе."""

    class DummyRepository:
        async def get_user(self, user_id: int) -> SimpleNamespace:
            return SimpleNamespace(
                balance=1250.0,
                total_withdrawn=500.0,
                payment_details="1234567812345678",
            )

        async def count_user_videos(self, user_id: int) -> int:
            return 7

    monkeypatch.setattr(balance, "BotRepository", lambda _: DummyRepository())
    monkeypatch.setattr(balance, "get_session_factory", lambda: None)

    text = await balance.build_balance_text(1001)

    assert "Загружено видео" not in text
