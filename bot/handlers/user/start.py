from aiogram import F
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import BotRepository, get_session_factory
from bot.keyboards.user_kb import get_main_menu_keyboard
from bot.services.telegram_safe import safe_callback_answer, safe_edit_message_text, safe_message_answer
from bot.ui.emojis import RATE_TEXT, STAR_TEXT

router = Router(name="user.start")

PLACEHOLDER_TEXT = "Раздел будет доступен на следующем этапе."

WELCOME_TEXT = (
    f"{STAR_TEXT} <b>Зарабатывай вместе с GG.Store с помощью коротких роликов!</b>\n\n"
    "Загружай короткие ролики с баннером GG.Store и получи возможность "
    "зарабатывать до <b>50 000 ₽</b> в месяц!\n\n"
    f"{RATE_TEXT} <b>Ставка:</b> 50 ₽ за 10 000 просмотров."
)


async def show_callback_screen(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup: object,
    disable_web_page_preview: bool = False,
) -> None:
    """Показывает экран по callback с fallback на новое сообщение."""

    if callback.message is None:
        return
    was_edited = await safe_edit_message_text(
        callback.message,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
    if was_edited:
        return
    await safe_message_answer(
        callback.message,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


@router.message(Command("start"))
@router.message(Command("menu"))
async def send_welcome(message: Message, state: FSMContext) -> None:
    """Создаёт пользователя в БД и показывает главное меню."""

    if message.from_user is None:
        return

    await state.clear()
    repository = BotRepository(get_session_factory())
    await repository.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    await safe_message_answer(
        message,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Открывает главное меню по отдельной кнопке."""

    await state.clear()
    await safe_callback_answer(callback)
    await show_callback_screen(
        callback,
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("menu:"))
async def handle_menu_placeholder(callback: CallbackQuery) -> None:
    """Показывает заглушку для разделов, которые будут реализованы позже."""

    await safe_callback_answer(callback, PLACEHOLDER_TEXT, show_alert=True)
