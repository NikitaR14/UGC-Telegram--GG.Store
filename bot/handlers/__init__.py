from aiogram import Router

from bot.handlers.admin.auth import router as auth_router
from bot.handlers.admin.export import router as export_router
from bot.handlers.admin.moderation import router as moderation_router
from bot.handlers.admin.withdrawals import router as admin_withdrawal_router
from bot.handlers.user.balance import router as balance_router
from bot.handlers.user.my_videos import router as my_videos_router
from bot.handlers.user.start import router as start_router
from bot.handlers.user.video import router as video_router
from bot.handlers.user.withdrawal import router as withdrawal_router
from bot.middlewares import create_subscription_middleware


def build_admin_router() -> Router:
    """Собирает корневой роутер администраторских сценариев."""

    admin_router = Router(name="admin")
    admin_router.include_router(auth_router)
    admin_router.include_router(export_router)
    admin_router.include_router(admin_withdrawal_router)
    admin_router.include_router(moderation_router)
    return admin_router


def build_user_router() -> Router:
    """Собирает корневой роутер пользовательских сценариев."""

    user_router = Router(name="user")
    subscription_middleware = create_subscription_middleware()
    user_router.message.outer_middleware(subscription_middleware)
    user_router.callback_query.outer_middleware(subscription_middleware)
    user_router.include_router(video_router)
    user_router.include_router(withdrawal_router)
    user_router.include_router(balance_router)
    user_router.include_router(my_videos_router)
    user_router.include_router(start_router)
    return user_router


def get_routers() -> list[Router]:
    """Возвращает список роутеров, подключаемых в приложении."""

    return [build_admin_router(), build_user_router()]
