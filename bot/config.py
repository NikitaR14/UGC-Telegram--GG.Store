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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный объект настроек."""

    return Settings()
