from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из .env."""

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_password: str = Field(alias="ADMIN_PASSWORD")
    database_url: str = Field(
        default="sqlite+aiosqlite:///./bot.db",
        alias="DATABASE_URL",
    )
    auto_init_db: bool = Field(default=False, alias="AUTO_INIT_DB")
    yandex_metrika_counter_id: str | None = Field(
        default=None,
        alias="YANDEX_METRIKA_COUNTER_ID",
    )
    yandex_metrika_secret_token: str | None = Field(
        default=None,
        alias="YANDEX_METRIKA_SECRET_TOKEN",
    )
    yandex_metrika_base_url: str = Field(
        default="https://t.me/ggstore_bot",
        alias="YANDEX_METRIKA_BASE_URL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный объект настроек."""

    return Settings()
