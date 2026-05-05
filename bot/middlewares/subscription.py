from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.db import BotRepository, get_session_factory
ADMIN_MODE_TEXT = "Вы в режиме администратора. Используйте /user для выхода."


class SubscriptionMiddleware(BaseMiddleware):
    """Блокирует user-flow, если пользователь находится в режиме администратора."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Блокирует обработку, если пользователь находится в режиме администратора."""

        user_id = self._extract_user_id(event)
        if user_id is None:
            return await handler(event, data)

        if await self._is_admin_session(user_id):
            await self._send_admin_mode_notice(event)
            return None

        return await handler(event, data)

    def _extract_user_id(self, event: TelegramObject) -> int | None:
        """Извлекает user_id из Message или CallbackQuery."""

        if isinstance(event, Message) and event.from_user is not None:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user is not None:
            return event.from_user.id
        return None

    async def _is_admin_session(self, user_id: int) -> bool:
        """Проверяет, включён ли для пользователя режим администратора."""

        repository = BotRepository(get_session_factory())
        user = await repository.get_user(user_id)
        return bool(user and user.is_admin_session)

    async def _send_admin_mode_notice(self, event: TelegramObject) -> None:
        """Сообщает, что пользователь находится в режиме администратора."""

        if isinstance(event, Message):
            await event.answer(ADMIN_MODE_TEXT)
            return

        if isinstance(event, CallbackQuery):
            await event.answer(ADMIN_MODE_TEXT, show_alert=True)


def create_subscription_middleware() -> SubscriptionMiddleware:
    """Создаёт middleware пользовательского режима."""

    return SubscriptionMiddleware()
