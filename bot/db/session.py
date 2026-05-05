from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import get_settings
from bot.db.models import Base

engine: AsyncEngine | None = None
session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Возвращает singleton async engine для приложения."""

    global engine
    if engine is None:
        settings = get_settings()
        engine = create_async_engine(settings.database_url, echo=False)
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику async-сессий SQLAlchemy."""

    global session_factory
    if session_factory is None:
        session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
        )
    return session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Предоставляет async-сессию в виде генератора."""

    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_database() -> None:
    """Создаёт таблицы БД для локального dev-режима без миграций."""

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    """Корректно закрывает соединения с базой данных."""

    global engine, session_factory
    if engine is not None:
        await engine.dispose()
    engine = None
    session_factory = None
