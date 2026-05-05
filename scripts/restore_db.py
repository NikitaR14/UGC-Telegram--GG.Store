from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from bot.config import get_settings
from scripts.backup_db import (
    POSTGRES_ASYNC_PREFIX,
    POSTGRES_SYNC_PREFIX,
    SQLITE_URL_PREFIX,
    resolve_sqlite_path,
    to_sync_postgres_url,
)

RESTORE_BACKUP_SUFFIX_FORMAT = "%Y%m%d_%H%M%S"


def configure_logger() -> None:
    """Настраивает вывод логов для restore-скрипта."""

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{level} | {message}")


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""

    parser = argparse.ArgumentParser(description="Восстанавливает базу данных из backup.")
    parser.add_argument("input", help="Путь к backup-файлу.")
    return parser.parse_args()


def main() -> int:
    """Восстанавливает SQLite или PostgreSQL в зависимости от DATABASE_URL."""

    configure_logger()
    args = parse_args()
    database_url = get_settings().database_url
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        logger.error("Restore failed | backup_not_found={}", input_path)
        return 1

    if database_url.startswith(SQLITE_URL_PREFIX):
        restore_sqlite_database(database_url, input_path)
        return 0
    if database_url.startswith((POSTGRES_ASYNC_PREFIX, POSTGRES_SYNC_PREFIX)):
        restore_postgres_database(database_url, input_path)
        return 0

    logger.error("Restore failed | unsupported_database_url")
    return 1


def restore_sqlite_database(database_url: str, input_path: Path) -> None:
    """Восстанавливает SQLite backup и сохраняет копию текущей базы."""

    target_path = resolve_sqlite_path(database_url)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        backup_path = build_restore_backup_path(target_path)
        shutil.copy2(target_path, backup_path)
        logger.info("Existing SQLite database backed up | backup={}", backup_path)
    shutil.copy2(input_path, target_path)
    logger.info("SQLite database restored | source={}", input_path)


def restore_postgres_database(database_url: str, input_path: Path) -> None:
    """Восстанавливает PostgreSQL backup через pg_restore."""

    sync_url = to_sync_postgres_url(database_url)
    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        f"--dbname={sync_url}",
        str(input_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pg_restore failed")
    logger.info("PostgreSQL database restored | source={}", input_path)


def build_restore_backup_path(target_path: Path) -> Path:
    """Создаёт имя backup-файла перед восстановлением существующей SQLite базы."""

    timestamp = datetime.now().strftime(RESTORE_BACKUP_SUFFIX_FORMAT)
    return target_path.with_suffix(f"{target_path.suffix}.pre_restore_{timestamp}.bak")


if __name__ == "__main__":
    raise SystemExit(main())
