from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.ui.emojis import (
    BALANCE_BUTTON_ICON_ID,
    BANNERS_BUTTON_ICON_ID,
    CLIPS_BUTTON_ICON_ID,
    COMMUNITY_BUTTON_ICON_ID,
    CARD_BUTTON_ICON_ID,
    GGSTORE_BUTTON_ICON_ID,
    LEFT_ARROW_BUTTON_ICON_ID,
    PAYMENTS_BUTTON_ICON_ID,
    RIGHT_ARROW_BUTTON_ICON_ID,
    SUPPORT_BUTTON_ICON_ID,
    TERMS_BUTTON_ICON_ID,
    USDT_BUTTON_ICON_ID,
    VIDEO_BUTTON_ICON_ID,
)

COMMUNITY_URL = "https://t.me/ggstore_hub"
SUPPORT_URL = "https://t.me/ggstore_support"
BANNERS_URL = (
    "https://drive.google.com/drive/folders/1mO-3VxlnzKgIDRvRngZEsKlg54rT1iPt?usp=sharing"
)
TERMS_URL = (
    "https://docs.google.com/document/d/1g-WjQ5IC8mzoyJNnwwLKuW3W_opqpd5B9M471J40apo/edit?usp=sharing"
)


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает inline-клавиатуру главного меню пользователя."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить видео",
                    icon_custom_emoji_id=VIDEO_BUTTON_ICON_ID,
                    callback_data="menu:add_video",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Мои видео",
                    icon_custom_emoji_id=CLIPS_BUTTON_ICON_ID,
                    callback_data="menu:my_videos",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Баланс",
                    icon_custom_emoji_id=BALANCE_BUTTON_ICON_ID,
                    callback_data="menu:balance",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Сообщество",
                    icon_custom_emoji_id=COMMUNITY_BUTTON_ICON_ID,
                    url=COMMUNITY_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Поддержка",
                    icon_custom_emoji_id=SUPPORT_BUTTON_ICON_ID,
                    url=SUPPORT_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Скачать баннеры",
                    icon_custom_emoji_id=BANNERS_BUTTON_ICON_ID,
                    callback_data="menu:banners",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Условия",
                    icon_custom_emoji_id=TERMS_BUTTON_ICON_ID,
                    url=TERMS_URL,
                ),
            ],
        ],
    )


def get_banners_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру со ссылкой на баннеры и меню."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть баннеры",
                    icon_custom_emoji_id=BANNERS_BUTTON_ICON_ID,
                    url=BANNERS_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="menu:main",
                ),
            ],
        ],
    )


def get_subscription_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру с кнопкой подписки на канал."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подписаться на GG.Store",
                    url=channel_url,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Проверить подписку",
                    callback_data="subscription:check",
                ),
            ],
        ],
    )


def get_add_video_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру сценария добавления видео."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="video:add:back",
                ),
            ],
        ],
    )


def get_return_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает кнопку перехода в главное меню."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="menu:main",
                ),
            ],
        ],
    )


def get_return_to_my_videos_keyboard() -> InlineKeyboardMarkup:
    """Возвращает кнопку перехода в раздел с видео пользователя."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Мои видео",
                    callback_data="menu:my_videos",
                ),
            ],
        ],
    )


def get_my_videos_keyboard(
    page: int,
    total_pages: int,
    has_items: bool,
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру истории видео с пагинацией."""

    inline_keyboard: list[list[InlineKeyboardButton]] = []
    if has_items:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{page}/{total_pages}",
                    callback_data="videos:noop",
                ),
            ],
        )
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id=LEFT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"videos:page:{max(page - 1, 1)}",
                ),
                InlineKeyboardButton(
                    text="Вперёд",
                    icon_custom_emoji_id=RIGHT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"videos:page:{min(page + 1, total_pages)}",
                ),
            ],
        )
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Главное меню",
                callback_data="videos:back",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def get_balance_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру экрана баланса."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить способ вывода",
                    icon_custom_emoji_id=CARD_BUTTON_ICON_ID,
                    callback_data="balance:change_method",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="История выплат",
                    icon_custom_emoji_id=PAYMENTS_BUTTON_ICON_ID,
                    callback_data="balance:history",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="balance:back",
                ),
            ],
        ],
    )


def get_payment_methods_keyboard(back_only: bool = False) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру выбора способа вывода."""

    inline_keyboard: list[list[InlineKeyboardButton]] = []
    if not back_only:
        inline_keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Банковская карта",
                        icon_custom_emoji_id=CARD_BUTTON_ICON_ID,
                        callback_data="balance:method:card",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="USDT TRC-20",
                        icon_custom_emoji_id=USDT_BUTTON_ICON_ID,
                        callback_data="balance:method:usdt",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Баланс gg.store",
                        icon_custom_emoji_id=GGSTORE_BUTTON_ICON_ID,
                        callback_data="balance:method:ggstore",
                    ),
                ],
            ],
        )
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="balance:return",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def get_withdrawals_keyboard(
    page: int,
    total_pages: int,
    has_items: bool,
) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру истории выплат."""

    inline_keyboard: list[list[InlineKeyboardButton]] = []
    if has_items:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{page}/{total_pages}",
                    callback_data="withdrawals:noop",
                ),
            ],
        )
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="Назад",
                    icon_custom_emoji_id=LEFT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"withdrawals:page:{max(page - 1, 1)}",
                ),
                InlineKeyboardButton(
                    text="Вперёд",
                    icon_custom_emoji_id=RIGHT_ARROW_BUTTON_ICON_ID,
                    callback_data=f"withdrawals:page:{min(page + 1, total_pages)}",
                ),
            ],
        )
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Главное меню",
                callback_data="withdrawals:back",
            ),
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
