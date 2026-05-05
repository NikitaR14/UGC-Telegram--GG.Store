from aiogram import Bot, F
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommandScopeChat, CallbackQuery, Message

from bot.db import BotRepository, get_session_factory
from bot.keyboards.user_kb import get_main_menu_keyboard
from bot.ui.emojis import RATE_TEXT, STAR_TEXT

router = Router(name="user.start")

PLACEHOLDER_TEXT = "Раздел будет доступен на следующем этапе."

WELCOME_TEXT = (
    f"{STAR_TEXT} <b>Зарабатывай вместе с GG.Store с помощью коротких роликов!</b>\n\n"
    "Загружай короткие ролики с баннером GG.Store и получи возможность "
    "зарабатывать до <b>50 000 ₽</b> в месяц!\n\n"
    f"{RATE_TEXT} <b>Ставка:</b> 250 ₽ за 1 000 просмотров."
)


async def clear_chat_commands(chat_id: int, bot: Bot) -> None:
    """Удаляет персональные команды для конкретного чата."""

    await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))


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
    await clear_chat_commands(message.from_user.id, message.bot)
    await message.answer(
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Открывает главное меню по отдельной кнопке."""

    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await clear_chat_commands(callback.from_user.id, callback.bot)
        await callback.message.answer(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("menu:"))
async def handle_menu_placeholder(callback: CallbackQuery) -> None:
    """Показывает заглушку для разделов, которые будут реализованы позже."""

    await callback.answer(PLACEHOLDER_TEXT, show_alert=True)
