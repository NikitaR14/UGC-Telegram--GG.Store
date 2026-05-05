from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from loguru import logger

from bot.config import get_settings

SQLITE_URL_PREFIX = "sqlite+aiosqlite:///"
POSTGRES_ASYNC_PREFIX = "postgresql+asyncpg://"
POSTGRES_SYNC_PREFIX = "postgresql://"


def configure_logger() -> None:
    """Настраивает вывод логов для backup-скрипта."""

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{level} | {message}")


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""

    parser = argparse.ArgumentParser(description="Создаёт резервную копию базы данных.")
    parser.add_argument("output", help="Путь для backup-файла.")
    return parser.parse_args()


def main() -> int:
    """Создаёт backup SQLite или PostgreSQL в зависимости от DATABASE_URL."""

    configure_logger()
    args = parse_args()
    database_url = get_settings().database_url
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if database_url.startswith(SQLITE_URL_PREFIX):
        backup_sqlite_database(database_url, output_path)
        return 0
    if database_url.startswith((POSTGRES_ASYNC_PREFIX, POSTGRES_SYNC_PREFIX)):
        backup_postgres_database(database_url, output_path)
        return 0

    logger.error("Backup failed | unsupported_database_url")
    return 1


def backup_sqlite_database(database_url: str, output_path: Path) -> None:
    """Создаёт backup SQLite через копирование файла базы данных."""

    source_path = resolve_sqlite_path(database_url)
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite database file not found: {source_path}")
    shutil.copy2(source_path, output_path)
    logger.info("SQLite backup created | output={}", output_path)


def backup_postgres_database(database_url: str, output_path: Path) -> None:
    """Создаёт backup PostgreSQL через pg_dump."""

    sync_url = to_sync_postgres_url(database_url)
    command = [
        "pg_dump",
        "--format=custom",
        f"--file={output_path}",
        sync_url,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pg_dump failed")
    logger.info("PostgreSQL backup created | output={}", output_path)


def resolve_sqlite_path(database_url: str) -> Path:
    """Преобразует SQLite URL в абсолютный путь к файлу базы данных."""

    raw_path = database_url.removeprefix(SQLITE_URL_PREFIX)
    return Path(raw_path).expanduser().resolve()


def to_sync_postgres_url(database_url: str) -> str:
    """Преобразует asyncpg URL в совместимый sync URL для pg_dump/pg_restore."""

    if database_url.startswith(POSTGRES_ASYNC_PREFIX):
        return database_url.replace(POSTGRES_ASYNC_PREFIX, POSTGRES_SYNC_PREFIX, 1)
    return database_url


if __name__ == "__main__":
    raise SystemExit(main())
