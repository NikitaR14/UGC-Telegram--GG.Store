from __future__ import annotations

import asyncio
import sys

from loguru import logger
from sqlalchemy import inspect, text

from bot.config import get_settings
from bot.db.session import close_database, get_engine

REQUIRED_TABLES = {
    "alembic_version",
    "payment_history",
    "users",
    "videos",
    "withdrawals",
    "withdrawal_request_items",
    "withdrawal_requests",
}


def configure_logger() -> None:
    """Настраивает компактный вывод логов для служебной проверки."""

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{level} | {message}")


async def main() -> int:
    """Проверяет конфиг приложения и доступность схемы базы данных."""

    configure_logger()
    try:
        settings = get_settings()
        logger.info("Settings loaded | auto_init_db={}", settings.auto_init_db)

        async with get_engine().begin() as connection:
            await connection.execute(text("SELECT 1"))
            table_names = set(await connection.run_sync(get_table_names))

        missing_tables = sorted(REQUIRED_TABLES - table_names)
        if missing_tables:
            logger.error("Healthcheck failed | missing_tables={}", ", ".join(missing_tables))
            return 1

        logger.info("Database reachable | tables_ok={}", ", ".join(sorted(REQUIRED_TABLES)))
        logger.info("Healthcheck passed")
        return 0
    except Exception as error:
        logger.error("Healthcheck failed | error={}", str(error))
        return 1
    finally:
        await close_database()


def get_table_names(connection) -> list[str]:
    """Возвращает список таблиц из текущего подключения."""

    inspector = inspect(connection)
    return inspector.get_table_names()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
