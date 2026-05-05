# UGC Telegram-бот GG.Store

Telegram-бот для приёма UGC-видео с TikTok и YouTube Shorts, модерации заявок и учёта выплат пользователям.

## Стек

- `Python 3.11+`
- `aiogram 3.x`
- `SQLAlchemy async`
- `aiosqlite` для локальной разработки
- `PostgreSQL + asyncpg` для стабильного деплоя
- `alembic` для миграций
- `loguru`
- `tenacity`

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Заполните в `.env`:

- `BOT_TOKEN`
- `ADMIN_PASSWORD`
- `DATABASE_URL`

## Работа со схемой БД

Для новой базы:

```bash
alembic upgrade head
```

Для уже существующей локальной базы, которая была создана старым способом через ORM:

```bash
alembic stamp head
```

`AUTO_INIT_DB=true` оставлен только для локальной отладки без миграций. Для деплоя его нужно держать в значении `false`.

## Запуск бота

```bash
python3 -m bot.main
```

## Быстрая проверка перед деплоем

Проверка тестов:

```bash
python3 -m pytest
```

Проверка конфигурации и схемы БД:

```bash
python3 -m scripts.healthcheck
```

## Backup и restore

Для SQLite:

```bash
python3 -m scripts.backup_db backups/ggstore.sqlite3
python3 -m scripts.restore_db backups/ggstore.sqlite3
```

Для PostgreSQL используются `pg_dump` и `pg_restore` через эти же скрипты. На сервере должны быть доступны соответствующие CLI-утилиты.

Перед restore SQLite текущая база автоматически копируется в файл вида:

```text
bot.db.pre_restore_YYYYMMDD_HHMMSS.bak
```

## Минимальный преддеплойный чек-лист

1. Установлены зависимости из `requirements.txt`.
2. Заполнен `.env` без тестовых значений.
3. Выполнен `alembic upgrade head`.
4. Прошёл `python3 -m pytest`.
5. Прошёл `python3 -m scripts.healthcheck`.
6. Проверен сценарий backup/restore для целевой среды.
7. Прогнан ручной smoke-test в Telegram:
   - `/start`
   - отправка валидной и невалидной ссылки
   - `Мои видео`
   - `Баланс` и реквизиты
   - `/admin`
   - `Принять`
   - `Отклонить`
   - `Оплачено`

## Постдеплойная проверка

1. Запустить `python3 -m scripts.healthcheck`.
2. Проверить лог старта бота без traceback.
3. Убедиться, что backup-скрипт запускается в целевой среде.
4. Отправить тестовую заявку.
5. Проверить, что она дошла до админки.
6. Проверить цикл `approved -> paid`.
