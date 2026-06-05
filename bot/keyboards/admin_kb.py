from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.ui.emojis import (
    CLIPS_BUTTON_ICON_ID,
    INBOX_BUTTON_ICON_ID,
    ERROR_BUTTON_ICON_ID,
    LEFT_ARROW_BUTTON_ICON_ID,
    PAYMENTS_BUTTON_ICON_ID,
    RIGHT_ARROW_BUTTON_ICON_ID,
    SUCCESS_BUTTON_ICON_ID,
)


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Возвращает главное меню админ-панели."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Новые заявки",
                    icon_custom_emoji_id=INBOX_BUTTON_ICON_ID,
                    callback_data="admin:menu:pending",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Одобренные",
                    icon_custom_emoji_id=SUCCESS_BUTTON_ICON_ID,
                    callback_data="admin:menu:approved",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Оплаченные",
                    icon_custom_emoji_id=PAYMENTS_BUTTON_ICON_ID,
                    callback_data="admin:menu:paid",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отклонённые",
                    icon_custom_emoji_id=ERROR_BUTTON_ICON_ID,
                    callback_data="admin:menu:rejected",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Все видео",
                    icon_custom_emoji_id=CLIPS_BUTTON_ICON_ID,
                    callback_data="admin:menu:all",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Выйти в user",
                    callback_data="admin:exit_user",
                ),
            ],
        ],
    )


def get_admin_video_keyboard(video_id: int) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру модерации новой заявки."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Принять",
                    icon_custom_emoji_id=SUCCESS_BUTTON_ICON_ID,
                    callback_data=f"admin:approve:{video_id}",
                ),
                InlineKeyboardButton(
                    text="Отклонить",
                    icon_custom_emoji_id=ERROR_BUTTON_ICON_ID,
                    callback_data=f"admin:reject:{video_id}",
                ),
            ],
        ],
    )


def get_admin_list_keyboard(
    status: str,
    page: int,
    total_pages: int,
    items: list[tuple[int, str]],
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру списка заявок с пагинацией."""

    rows: list[list[InlineKeyboardButton]] = []
    for video_id, label in items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"admin:view:{status}:{page}:{video_id}",
                ),
            ],
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=f"{page}/{total_pages}",
                callback_data="admin:list:noop",
            ),
        ],
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                icon_custom_emoji_id=LEFT_ARROW_BUTTON_ICON_ID,
                callback_data=f"admin:list:{status}:{max(page - 1, 1)}",
            ),
            InlineKeyboardButton(
                text="Вперёд",
                icon_custom_emoji_id=RIGHT_ARROW_BUTTON_ICON_ID,
                callback_data=f"admin:list:{status}:{min(page + 1, total_pages)}",
            ),
        ],
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Разделы",
                callback_data="admin:dashboard",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_detail_keyboard(
    video_id: int,
    current_status: str,
    back_status: str,
    back_page: int,
    can_mark_paid: bool = True,
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру карточки заявки с действиями."""

    rows: list[list[InlineKeyboardButton]] = []
    if current_status == "pending":
        rows.append(
            [
                InlineKeyboardButton(
                    text="Принять",
                    icon_custom_emoji_id=SUCCESS_BUTTON_ICON_ID,
                    callback_data=f"admin:approve:{video_id}:{back_status}:{back_page}",
                ),
                InlineKeyboardButton(
                    text="Отклонить",
                    icon_custom_emoji_id=ERROR_BUTTON_ICON_ID,
                    callback_data=f"admin:reject:{video_id}:{back_status}:{back_page}",
                ),
            ],
        )
    elif current_status == "approved" and can_mark_paid:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Оплачено",
                    icon_custom_emoji_id=PAYMENTS_BUTTON_ICON_ID,
                    callback_data=f"admin:paid:{video_id}:{back_status}:{back_page}",
                ),
            ],
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="К списку",
                callback_data=f"admin:list:{back_status}:{back_page}",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_paid_keyboard(video_id: int) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру подтверждения выплаты."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оплачено",
                    icon_custom_emoji_id=PAYMENTS_BUTTON_ICON_ID,
                    callback_data=f"admin:paid:{video_id}",
                ),
            ],
        ],
    )


def get_admin_waiting_details_keyboard(
    video_id: int,
    back_status: str,
    back_page: int,
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для сообщения об ожидании реквизитов."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К заявке",
                    callback_data=f"admin:view:{back_status}:{back_page}:{video_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="В админку",
                    callback_data="admin:dashboard",
                ),
            ],
        ],
    )


def get_admin_all_videos_keyboard() -> InlineKeyboardMarkup:
    """Возвращает кнопку перехода в раздел со всеми видео."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Все видео",
                    callback_data="admin:all_videos:1",
                ),
            ],
        ],
    )


def get_admin_all_videos_list_keyboard(
    page: int,
    total_pages: int,
    has_items: bool,
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру раздела со всеми видео пользователей."""

    rows: list[list[InlineKeyboardButton]] = []
    if has_items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{page}/{total_pages}",
                    callback_data="admin:all_videos:noop",
                ),
            ],
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id=LEFT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"admin:all_videos:{max(page - 1, 1)}",
                ),
                InlineKeyboardButton(
                    text="Вперёд",
                    icon_custom_emoji_id=RIGHT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"admin:all_videos:{min(page + 1, total_pages)}",
                ),
            ],
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Разделы",
                callback_data="admin:dashboard",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
