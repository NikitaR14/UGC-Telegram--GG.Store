from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.types import InlineKeyboardMarkup
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.config import get_settings
from bot.db import BotRepository, User, Video, get_session_factory
from bot.services.video import shorten_video_title
from bot.ui.emojis import BALANCE_TEXT, CARD_TEXT, DETAILS_ADDED_TEXT, ERROR_TEXT, SUCCESS_TEXT, STAR_TEXT, USDT_TEXT

WITHDRAWAL_DAYS = 3


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(TelegramNetworkError),
    reraise=True,
)
async def send_notification(bot: Bot, chat_id: int, text: str) -> None:
    """Отправляет уведомление пользователю с retry."""

    await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(TelegramNetworkError),
    reraise=True,
)
async def send_admin_notification(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Отправляет сообщение администратору с retry на сетевые ошибки."""

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def notify_video_approved(bot: Bot, user: User, video: Video) -> None:
    """Уведомляет пользователя об одобрении заявки."""

    title = shorten_video_title(video.title or video.url)
    if user.payment_details:
        text = (
            f"{SUCCESS_TEXT} <b>Поздравляем!</b>\n\n"
            "Заявка на вывод средств по видео "
            f"<a href=\"{video.url}\">{title}</a> была принята.\n"
            f"Ожидайте начисление <b>{int(video.payout_amount)} ₽</b> на счёт "
            f"<b>**** {user.payment_details[-4:]}</b>!"
        )
    else:
        text = (
            f"{SUCCESS_TEXT} <b>Поздравляем!</b>\n\n"
            "Заявка на вывод средств по видео "
            f"<a href=\"{video.url}\">{title}</a> была принята.\n"
            "Привяжите пожалуйста платёжные реквизиты в меню «Баланс»."
        )

    await _safe_notify(bot, user.user_id, text, "approved")


async def notify_video_rejected(bot: Bot, user: User, video: Video) -> None:
    """Уведомляет пользователя об отклонении заявки."""

    title = shorten_video_title(video.title or video.url)
    text = (
        f"{ERROR_TEXT} <b>Упс...</b>\n\n"
        "Похоже, заявка на вывод средств по видео "
        f"<a href=\"{video.url}\">{title}</a> была отклонена.\n"
        "<b>Причина отказа:</b>\n"
        f"<blockquote>{video.reject_reason or 'Не указана'}</blockquote>"
    )
    await _safe_notify(bot, user.user_id, text, "rejected")


async def notify_video_paid(bot: Bot, user: User, video: Video) -> None:
    """Уведомляет пользователя о подтверждённой выплате."""

    title = shorten_video_title(video.title or video.url)
    text = (
        f"{BALANCE_TEXT} <b>Выплата отправлена!</b>\n\n"
        f"По видео <a href=\"{video.url}\">{title}</a> подтверждена выплата "
        f"<b>{int(video.payout_amount)} ₽</b>."
    )
    await _safe_notify(bot, user.user_id, text, "paid")


async def notify_admins_about_payment_details(
    bot: Bot,
    user: User,
    approved_video_ids: list[int],
) -> None:
    """Уведомляет администраторов, что пользователь добавил реквизиты."""

    repository = BotRepository(get_session_factory())
    admin_ids = await repository.get_active_admin_ids()
    username_label = f"@{user.username}" if user.username else "без username"
    method_label = format_payment_method(user.payment_method)
    details_label = user.payment_details or "не указаны"
    applications_line = build_applications_line(approved_video_ids)
    text = (
        f"{DETAILS_ADDED_TEXT} <b>Пользователь добавил реквизиты</b>\n\n"
        f"<b>Пользователь:</b> {username_label} (id: {user.user_id})\n"
        f"{applications_line}\n"
        "<b>Раздел:</b> Одобренные\n"
        f"<b>Способ вывода:</b> {method_label}\n"
        f"<b>Реквизиты:</b> <code>{escape(details_label)}</code>\n"
        "<b>Статус:</b> реквизиты добавлены"
    )

    for admin_id in admin_ids:
        await _safe_notify_admin(
            bot=bot,
            admin_id=admin_id,
            text=text,
            operation="payment_details",
        )


async def _safe_notify(bot: Bot, user_id: int, text: str, operation: str) -> None:
    """Отправляет уведомление и логирует конкретные Telegram-ошибки."""

    try:
        await send_notification(bot, user_id, text)
    except TelegramForbiddenError as error:
        logger.warning(
            "Notification forbidden | user={} operation={} error={}",
            user_id,
            operation,
            str(error),
        )
    except TelegramBadRequest as error:
        logger.warning(
            "Notification bad request | user={} operation={} error={}",
            user_id,
            operation,
            str(error),
        )
    except TelegramNetworkError as error:
        logger.warning(
            "Notification network error | user={} operation={} error={}",
            user_id,
            operation,
            str(error),
        )


async def _safe_notify_admin(
    bot: Bot,
    admin_id: int,
    text: str,
    operation: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Отправляет сообщение администратору и логирует Telegram-ошибки."""

    try:
        await send_admin_notification(
            bot=bot,
            chat_id=admin_id,
            text=text,
            reply_markup=reply_markup,
        )
    except TelegramForbiddenError as error:
        logger.warning(
            "Admin notification forbidden | admin={} operation={} error={}",
            admin_id,
            operation,
            str(error),
        )
    except TelegramBadRequest as error:
        logger.warning(
            "Admin notification bad request | admin={} operation={} error={}",
            admin_id,
            operation,
            str(error),
        )
    except TelegramNetworkError as error:
        logger.warning(
            "Admin notification network error | admin={} operation={} error={}",
            admin_id,
            operation,
            str(error),
        )


def format_payment_method(payment_method: str | None) -> str:
    """Возвращает понятную подпись способа вывода."""

    if payment_method == "card":
        return f"{CARD_TEXT} Банковская карта"
    if payment_method == "usdt":
        return f"{USDT_TEXT} USDT TRC-20"
    if payment_method == "ggstore":
        return f"{STAR_TEXT} Баланс gg.store"
    return "Не указан"


def build_applications_line(approved_video_ids: list[int]) -> str:
    """Формирует строку с номерами заявок для админского уведомления."""

    if not approved_video_ids:
        return "<b>Заявки:</b> не найдены"
    if len(approved_video_ids) == 1:
        return f"<b>Заявка:</b> #{approved_video_ids[0]:05d}"

    numbers = ", ".join(f"#{video_id:05d}" for video_id in approved_video_ids)
    return f"<b>Заявки:</b> {numbers}"
