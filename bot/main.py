from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)
from loguru import logger

from bot.config import get_settings
from bot.db import close_database, init_database
from bot.handlers import get_routers
from bot.services.telegram_safe import safe_delete_my_commands, safe_set_my_commands
from bot.services.video_monitor import run_video_views_monitor


def configure_logger() -> None:
    """Настраивает единый вывод логов приложения."""

    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )


def build_dispatcher() -> Dispatcher:
    """Создаёт диспетчер и подключает все доступные роутеры."""

    dispatcher = Dispatcher()
    for router in get_routers():
        dispatcher.include_router(router)
    return dispatcher


async def setup_bot_commands(bot: Bot) -> None:
    """Регистрирует актуальное меню команд для пользователей."""

    user_commands = [
        BotCommand(command="start", description="Запустить бота"),
    ]

    await safe_delete_my_commands(bot)
    await safe_delete_my_commands(bot, scope=BotCommandScopeAllPrivateChats())
    await safe_set_my_commands(
        bot,
        user_commands,
        scope=BotCommandScopeDefault(),
    )


async def setup_bot_commands_background(bot: Bot) -> None:
    """Обновляет команды бота в фоне, не задерживая старт polling."""

    try:
        await setup_bot_commands(bot)
    except Exception as error:
        logger.warning("Background bot command setup failed | error={}", str(error))


async def run_polling_forever(dispatcher: Dispatcher, bot: Bot) -> None:
    """Держит polling активным и переживает временные сетевые сбои Telegram."""

    retry_delay_seconds = 3
    while True:
        try:
            logger.info("Starting bot polling")
            await dispatcher.start_polling(bot)
            return
        except TelegramNetworkError as error:
            logger.warning(
                "Polling interrupted by Telegram network error | retry_in={}s error={}",
                retry_delay_seconds,
                str(error),
            )
            await asyncio.sleep(retry_delay_seconds)


async def main() -> None:
    """Запускает Telegram-бота."""

    configure_logger()
    settings = get_settings()
    if settings.auto_init_db:
        await init_database()
        logger.warning("Database schema auto-init enabled for local development")
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    asyncio.create_task(setup_bot_commands_background(bot))
    asyncio.create_task(run_video_views_monitor(bot))

    logger.info("Bot process initialized")
    try:
        await run_polling_forever(dispatcher, bot)
    finally:
        await bot.session.close()
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
