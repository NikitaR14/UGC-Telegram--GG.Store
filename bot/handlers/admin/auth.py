from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.db import BotRepository, get_session_factory
from bot.handlers.user.start import WELCOME_TEXT
from bot.keyboards.admin_kb import get_admin_dashboard_keyboard
from bot.keyboards.user_kb import get_main_menu_keyboard
from bot.ui.emojis import SUPPORT_TEXT

router = Router(name="admin.auth")

ADMIN_PROMPT_TEXT = (
    "Добро пожаловать в панель UGC-бота GG.Store!\n"
    "Пожалуйста, введите пароль:"
)
ADMIN_DASHBOARD_TEXT = (
    f"{SUPPORT_TEXT} <b>Панель администратора</b>\n\n"
    "Выберите раздел для работы с заявками."
)
ADMIN_EXIT_TEXT = "Режим администратора отключён."
WRONG_PASSWORD_TEXT = "Неверный пароль. Попробуйте ещё раз."


class AdminAuthState(StatesGroup):
    """Состояния входа администратора."""

    waiting_for_password = State()


@router.message(Command("admin"))
async def enter_admin_mode(message: Message, state: FSMContext) -> None:
    """Обрабатывает вход администратора в панель."""

    if message.from_user is None:
        return

    repository = BotRepository(get_session_factory())
    await repository.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    user = await repository.get_user(message.from_user.id)
    if user is not None and user.is_admin_session:
        await state.clear()
        await message.answer(
            ADMIN_DASHBOARD_TEXT,
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return

    await state.set_state(AdminAuthState.waiting_for_password)
    await message.answer(ADMIN_PROMPT_TEXT)


@router.message(Command("user"))
async def exit_admin_mode(message: Message, state: FSMContext) -> None:
    """Выключает режим администратора и возвращает пользователя в меню."""

    if message.from_user is None:
        return

    repository = BotRepository(get_session_factory())
    await repository.upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    user = await repository.get_user(message.from_user.id)
    if user is None or not user.is_admin_session:
        return
    await repository.set_admin_session(message.from_user.id, False)
    await state.clear()
    await message.answer(ADMIN_EXIT_TEXT)
    await message.answer(
        WELCOME_TEXT,
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "admin:exit_user")
async def exit_admin_mode_by_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Выключает режим администратора по кнопке панели."""

    if callback.from_user is None:
        return

    repository = BotRepository(get_session_factory())
    await repository.upsert_user(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
    )
    user = await repository.get_user(callback.from_user.id)
    if user is None or not user.is_admin_session:
        return
    await repository.set_admin_session(callback.from_user.id, False)
    await state.clear()
    await callback.answer("Режим администратора отключён.")
    if callback.message is not None:
        await callback.message.edit_text(
            WELCOME_TEXT,
            reply_markup=get_main_menu_keyboard(),
        )


@router.message(AdminAuthState.waiting_for_password)
async def handle_admin_password(message: Message, state: FSMContext) -> None:
    """Проверяет пароль и включает admin-сессию."""

    if message.from_user is None:
        return
    if not message.text:
        return

    settings = get_settings()
    if message.text != settings.admin_password:
        await message.answer(WRONG_PASSWORD_TEXT)
        return

    repository = BotRepository(get_session_factory())
    await repository.set_admin_session(message.from_user.id, True)
    await state.clear()
    await message.answer(
        ADMIN_DASHBOARD_TEXT,
        reply_markup=get_admin_dashboard_keyboard(),
    )
