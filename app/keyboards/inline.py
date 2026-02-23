from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.locales.translations import LANGUAGE_LABELS, tr
from app.services.catalog import PAYMENT_KEYS, PLAN_KEYS, PROTOCOL_KEYS, SERVER_KEYS


def main_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "menu_buy"), callback_data="menu:buy", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "menu_lang"), callback_data="menu:lang")],
        ]
    )


def language_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"lang:{code}")]
        for code, label in LANGUAGE_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plan_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"plan_{key}"), callback_data=f"plan:{key}")]
        for key in PLAN_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def server_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"server_{key}"), callback_data=f"server:{key}")]
        for key in SERVER_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:plan")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def protocol_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=key.title(), callback_data=f"protocol:{key}")]
        for key in PROTOCOL_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:server")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"payment_{key}"), callback_data=f"payment:{key}")]
        for key in PAYMENT_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:protocol")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "summary_pay"), callback_data="pay:start", style="success")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
            [InlineKeyboardButton(text=tr(lang, "menu_buy"), callback_data="menu:buy")],
        ]
    )


def payment_simulation_menu(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(lang, "pay_success"),
                    callback_data=f"pay:result:success:{order_id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(lang, "pay_failed"),
                    callback_data=f"pay:result:failed:{order_id}",
                    style="danger",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(lang, "pay_cancel"),
                    callback_data=f"pay:result:cancel:{order_id}",
                    style="danger",
                )
            ],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
        ]
    )


def payment_retry_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "pay_retry"), callback_data="pay:start", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
            [InlineKeyboardButton(text=tr(lang, "back_to_main"), callback_data="back:main")],
        ]
    )


def payment_done_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "menu_buy"), callback_data="menu:buy", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "back_to_main"), callback_data="back:main")],
        ]
    )


def cryptobot_invoice_menu(lang: str, order_id: int, invoice_id: int, pay_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "cryptobot_open_invoice"), url=pay_url)],
            [
                InlineKeyboardButton(
                    text=tr(lang, "cryptobot_check_payment"),
                    callback_data=f"pay:check:cryptobot:{order_id}:{invoice_id}",
                    style="primary",
                )
            ],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
        ]
    )
