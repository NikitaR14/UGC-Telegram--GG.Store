from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from loguru import logger

from bot.db import BotRepository, Video, get_session_factory
from bot.handlers.admin.moderation import is_valid_admin_callback, is_valid_admin_message
from bot.keyboards.admin_kb import get_admin_dashboard_keyboard
from bot.services.export import build_export_filename, create_videos_workbook
from bot.services.video import fetch_video_metrics

router = Router(name="admin.export")
APP_TIMEZONE = ZoneInfo("Europe/Kyiv")
REFRESH_CONCURRENCY = 5


class ExportState(StatesGroup):
    """Состояния ввода диапазона админской выгрузки."""

    waiting_for_start_date = State()
    waiting_for_end_date = State()


@router.callback_query(F.data == "admin:export:start")
async def start_export(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает начальную дату выгрузки."""

    if not await is_valid_admin_callback(callback):
        return
    await state.set_state(ExportState.waiting_for_start_date)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Введите начальную дату в формате ДД.ММ.ГГГГ:")


@router.message(ExportState.waiting_for_start_date)
async def accept_start_date(message: Message, state: FSMContext) -> None:
    """Сохраняет начальную дату и запрашивает конечную."""

    if not await is_valid_admin_message(message) or not message.text:
        return
    start_date = parse_date(message.text)
    if start_date is None:
        await message.answer("Неверная дата. Пример: 01.08.2026")
        return
    await state.update_data(start_date=start_date.isoformat())
    await state.set_state(ExportState.waiting_for_end_date)
    await message.answer("Введите конечную дату в формате ДД.ММ.ГГГГ:")


@router.message(ExportState.waiting_for_end_date)
async def accept_end_date(message: Message, state: FSMContext) -> None:
    """Проверяет диапазон и формирует Excel-файл."""

    if not await is_valid_admin_message(message) or not message.text:
        return
    end_date = parse_date(message.text)
    data = await state.get_data()
    start_date = parse_iso_date(data.get("start_date"))
    if end_date is None or start_date is None:
        await message.answer("Неверная дата. Пример: 31.08.2026")
        return
    if end_date < start_date:
        await message.answer("Конечная дата не может быть раньше начальной.")
        return
    await state.clear()
    await message.answer("Обновляю статистику и готовлю Excel-файл…")
    await generate_export(message, start_date, end_date)


async def generate_export(message: Message, start_date: date, end_date: date) -> None:
    """Обновляет метрики, фильтрует ролики и отправляет выгрузку."""

    repository = BotRepository(get_session_factory())
    created_from, created_to = build_utc_range(start_date, end_date)
    videos = await repository.get_videos_for_export(created_from, created_to)
    statuses = await refresh_export_metrics(repository, videos)
    eligible_videos = [video for video in videos if video.views_count >= 100_000]
    if not eligible_videos:
        await message.answer(
            "За указанный период нет подтверждённых роликов с 100 000+ просмотров.",
            reply_markup=get_admin_dashboard_keyboard(),
        )
        return
    try:
        with TemporaryDirectory(prefix="ggstore_export_") as directory:
            filename = build_export_filename(start_date, end_date)
            path = create_videos_workbook(
                eligible_videos,
                statuses,
                Path(directory) / filename,
            )
            await message.answer_document(
                FSInputFile(path, filename=filename),
                caption=f"Выгрузка за {start_date:%d.%m.%Y}–{end_date:%d.%m.%Y}",
                reply_markup=get_admin_dashboard_keyboard(),
            )
    except (OSError, ValueError) as error:
        logger.error("Excel export failed | error={}", str(error))
        await message.answer("Не удалось сформировать Excel-файл.")


async def refresh_export_metrics(
    repository: BotRepository,
    videos: list[Video],
) -> dict[int, str]:
    """Ограниченно-параллельно обновляет метрики кандидатов."""

    semaphore = asyncio.Semaphore(REFRESH_CONCURRENCY)

    async def refresh(video: Video) -> tuple[int, str]:
        async with semaphore:
            return await refresh_export_video(repository, video)

    results = await asyncio.gather(*(refresh(video) for video in videos))
    return dict(results)


async def refresh_export_video(
    repository: BotRepository,
    video: Video,
) -> tuple[int, str]:
    """Обновляет один ролик или сохраняет его последние данные."""

    metrics = await fetch_video_metrics(video.url)
    if metrics is None:
        return video.video_id, "Использованы последние данные"
    updated = await repository.update_video_metrics(
        video.video_id,
        metrics.views_count,
        metrics.likes_count,
        metrics.comments_count,
        metrics.shares_count,
    )
    if updated is None:
        return video.video_id, "Ошибка сохранения"
    copy_metrics(video, updated)
    return video.video_id, "Обновлено перед выгрузкой"


def copy_metrics(target: Video, source: Video) -> None:
    """Копирует обновлённые метрики в экспортную модель."""

    target.views_count = source.views_count
    target.likes_count = source.likes_count
    target.comments_count = source.comments_count
    target.shares_count = source.shares_count
    target.views_updated_at = source.views_updated_at


def build_utc_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Строит включительный локальный диапазон и переводит его в UTC."""

    local_start = datetime.combine(start_date, time.min, tzinfo=APP_TIMEZONE)
    local_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=APP_TIMEZONE)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def parse_date(value: str) -> date | None:
    """Разбирает дату формата ДД.ММ.ГГГГ."""

    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_iso_date(value: object) -> date | None:
    """Разбирает дату, сохранённую в FSM."""

    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
