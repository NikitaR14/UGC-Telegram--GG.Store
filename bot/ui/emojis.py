"""Централизованные эмодзи для текстов и кнопок Telegram-бота.

Для текстов сообщений можно использовать premium Telegram emoji через тег
``<tg-emoji ...>``. Для inline-кнопок Telegram пока не поддерживает HTML-разметку,
поэтому для них оставляем обычные Unicode-эмодзи, но тоже держим в одном месте.
"""


def premium_emoji(emoji_id: str, fallback: str) -> str:
    """Возвращает premium emoji в HTML-формате с fallback-символом."""

    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# Эмодзи для текстов сообщений.
STAR_TEXT = premium_emoji("5334864305261151558", "⭐️")
CARD_TEXT = premium_emoji("5472250091332993630", "💳")
VIDEO_TEXT = premium_emoji("5377490369615245128", "🆕")
CLIPS_TEXT = premium_emoji("5282843764451195532", "🖥")
BALANCE_TEXT = premium_emoji("5238132025323444613", "🏦")
PAYMENTS_TEXT = premium_emoji("5222160283195170007", "📂")
INBOX_TEXT = premium_emoji("5445355530111437729", "📤")
SUCCESS_TEXT = premium_emoji("5337006433084912502", "✅")
ERROR_TEXT = premium_emoji("5336769136141811523", "❌")
PIN_TEXT = premium_emoji("5420323339723881652", "⚠️")
TOOLS_TEXT = "🛠"
LIST_TEXT = premium_emoji("5222160283195170007", "📂")
USDT_TEXT = premium_emoji("5359437015752401733", "📱")
BANNERS_TEXT = premium_emoji("5372878055775683161", "📱")
COMMUNITY_TEXT = premium_emoji("5352567563454808495", "👀")
SUPPORT_TEXT = premium_emoji("5444965061749644170", "👨‍💻")
RATE_TEXT = premium_emoji("5201873447554145566", "💵")
DETAILS_ADDED_TEXT = premium_emoji("5337017423906226569", "🔴")
TERMS_TEXT = premium_emoji("5334544901428229844", "ℹ️")


# Эмодзи для inline-кнопок.
VIDEO_BUTTON = "🆕"
CLIPS_BUTTON = "🖥"
BALANCE_BUTTON = "👛"
COMMUNITY_BUTTON = "👥"
SUPPORT_BUTTON = "🆘"
BANNERS_BUTTON = "🖼"
CARD_BUTTON = "💳"
GAME_BUTTON = "🎮"
USDT_BUTTON = "📱"
PAYMENTS_BUTTON = "💸"
INBOX_BUTTON = "📤"
SUCCESS_BUTTON = "✅"
ERROR_BUTTON = "❌"
BACK_BUTTON = "←"
BACK_PAGE_BUTTON = "◀"
FORWARD_PAGE_BUTTON = "▶"
EXIT_BUTTON = "↩️"


# Идентификаторы premium emoji для кнопок.
CARD_BUTTON_ICON_ID = "5472250091332993630"
GGSTORE_BUTTON_ICON_ID = "5334864305261151558"
USDT_BUTTON_ICON_ID = "5359437015752401733"
BANNERS_BUTTON_ICON_ID = "5372878055775683161"
PAYMENTS_BUTTON_ICON_ID = "5222160283195170007"
COMMUNITY_BUTTON_ICON_ID = "5352567563454808495"
SUPPORT_BUTTON_ICON_ID = "5444965061749644170"
TERMS_BUTTON_ICON_ID = "5334544901428229844"
BALANCE_BUTTON_ICON_ID = "5238132025323444613"
VIDEO_BUTTON_ICON_ID = "5377490369615245128"
CLIPS_BUTTON_ICON_ID = "5282843764451195532"
RIGHT_ARROW_BUTTON_ICON_ID = "5300887377328243902"
LEFT_ARROW_BUTTON_ICON_ID = "5301207867787873145"
SUCCESS_BUTTON_ICON_ID = "5337006433084912502"
ERROR_BUTTON_ICON_ID = "5336769136141811523"
INBOX_BUTTON_ICON_ID = "5445355530111437729"
