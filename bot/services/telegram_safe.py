from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import BotCommand
from aiogram.types import CallbackQuery, Message
from loguru import logger
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

RetryResult = TypeVar("RetryResult")


async def _run_with_network_retry(
    operation: Callable[[], Awaitable[RetryResult]],
) -> RetryResult:
    """Повторяет Telegram-запрос при сетевых ошибках."""

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception_type(TelegramNetworkError),
        reraise=True,
    ):
        with attempt:
            return await operation()
    raise RuntimeError("Retry loop finished without result")


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    """Безопасно подтверждает callback, не валя процесс при timeout."""

    try:
        await _run_with_network_retry(
            lambda: callback.answer(text=text, show_alert=show_alert),
        )
        return True
    except TelegramBadRequest as error:
        error_text = str(error).lower()
        if "query is too old" in error_text or "query id is invalid" in error_text:
            logger.warning(
                "Telegram callback answer skipped for stale query | user={} data={} error={}",
                callback.from_user.id,
                callback.data,
                str(error),
            )
            return False
        raise
    except TelegramNetworkError as error:
        logger.warning(
            "Telegram callback answer skipped after retries | user={} data={} error={}",
            callback.from_user.id,
            callback.data,
            str(error),
        )
        return False


async def safe_message_answer(
    message: Message,
    text: str,
    *,
    reply_markup: object | None = None,
    disable_web_page_preview: bool = False,
) -> Message | None:
    """Безопасно отправляет новое сообщение."""

    try:
        return await _run_with_network_retry(
            lambda: message.answer(
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            ),
        )
    except TelegramNetworkError as error:
        logger.warning(
            "Telegram message answer skipped after retries | chat={} error={}",
            message.chat.id,
            str(error),
        )
        return None


async def safe_edit_message_text(
    message: Message,
    text: str,
    *,
    reply_markup: object | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    """Безопасно редактирует сообщение и сообщает, удалось ли это."""

    try:
        await _run_with_network_retry(
            lambda: message.edit_text(
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            ),
        )
        return True
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return True
        logger.warning(
            "Telegram edit_text fallback required | chat={} message_id={} error={}",
            message.chat.id,
            message.message_id,
            str(error),
        )
        return False
    except TelegramNetworkError as error:
        logger.warning(
            "Telegram edit_text skipped after retries | chat={} message_id={} error={}",
            message.chat.id,
            message.message_id,
            str(error),
        )
        return False


async def safe_delete_my_commands(bot: Bot, *, scope: object | None = None) -> bool:
    """Безопасно удаляет команды бота, не прерывая запуск при timeout."""

    try:
        await _run_with_network_retry(
            lambda: bot.delete_my_commands(scope=scope),
        )
        return True
    except TelegramNetworkError as error:
        logger.warning(
            "Telegram delete_my_commands skipped after retries | scope={} error={}",
            type(scope).__name__ if scope is not None else "default",
            str(error),
        )
        return False


async def safe_set_my_commands(
    bot: Bot,
    commands: list[BotCommand],
    *,
    scope: object | None = None,
) -> bool:
    """Безопасно устанавливает команды бота, не прерывая запуск при timeout."""

    try:
        await _run_with_network_retry(
            lambda: bot.set_my_commands(commands, scope=scope),
        )
        return True
    except TelegramNetworkError as error:
        logger.warning(
            "Telegram set_my_commands skipped after retries | scope={} error={}",
            type(scope).__name__ if scope is not None else "default",
            str(error),
        )
        return False
