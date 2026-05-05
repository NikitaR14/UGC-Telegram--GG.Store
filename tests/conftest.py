from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from bot.db.models import Base
from bot.db.repository import BotRepository


@pytest_asyncio.fixture
async def session_factory(tmp_path) -> AsyncIterator[async_sessionmaker]:
    """Поднимает отдельную временную базу данных для каждого теста."""

    database_path = tmp_path / "test_bot.db"
    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        echo=False,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def repository(
    session_factory: async_sessionmaker,
) -> AsyncIterator[BotRepository]:
    """Создаёт репозиторий поверх временной базы данных."""

    yield BotRepository(session_factory)
