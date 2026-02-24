from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.locales.translations import LANGUAGE_LABELS, tr
from app.services.catalog import (
    CUSTOM_DEVICE_OPTIONS,
    CUSTOM_MONTH_OPTIONS,
    PAYMENT_KEYS,
    PROTOCOL_KEYS,
    SERVER_KEYS,
    list_ready_options,
    list_ready_plans,
    ready_option_button_label,
    ready_plan_button_label,
)


def main_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "menu_buy"), callback_data="menu:buy", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "menu_account"), callback_data="menu:account")],
            [InlineKeyboardButton(text=tr(lang, "menu_lang"), callback_data="menu:lang")],
        ]
    )


def buy_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "buy_ready"), callback_data="buy:ready", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "buy_custom"), callback_data="buy:custom")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:main")],
        ]
    )


def language_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"lang:{code}")]
        for code, label in LANGUAGE_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_menu(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, "info_terms_btn"), callback_data="info:terms")],
        [InlineKeyboardButton(text=tr(lang, "info_privacy_btn"), callback_data="info:privacy")],
        [InlineKeyboardButton(text=tr(lang, "support_create"), callback_data="support:create")],
        [InlineKeyboardButton(text=tr(lang, "support_my"), callback_data="support:my")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text=tr(lang, "support_open_admin"), callback_data="support:open")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:account")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "menu_support"), callback_data="menu:support")],
            [InlineKeyboardButton(text=tr(lang, "menu_orders"), callback_data="menu:orders")],
            [InlineKeyboardButton(text=tr(lang, "menu_configs"), callback_data="menu:configs")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:main")],
        ]
    )


def ready_plan_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=ready_plan_button_label(plan), callback_data=f"ready_plan:{plan.code}")]
        for plan in list_ready_plans()
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "ready_details_btn"), callback_data="ready:info")])
    rows.append([InlineKeyboardButton(text=tr(lang, "buy_custom"), callback_data="buy:custom", style="primary")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ready_months_menu(lang: str, plan_code: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=ready_option_button_label(opt), callback_data=f"ready_month:{plan_code}:{opt.months}")]
        for opt in list_ready_options(plan_code)
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "buy_custom"), callback_data="buy:custom")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="buy:ready")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ready_info_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "buy_custom"), callback_data="buy:custom")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="buy:ready")],
        ]
    )


def custom_server_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"server_{key}"), callback_data=f"custom_server:{key}")]
        for key in SERVER_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_protocol_menu(lang: str, server: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=key.title(), callback_data=f"custom_protocol:{server}:{key}")]
        for key in PROTOCOL_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="buy:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_months_menu(lang: str, server: str, protocol: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{m} мес", callback_data=f"custom_month:{server}:{protocol}:{m}")]
        for m in CUSTOM_MONTH_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=f"custom_server:{server}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def custom_devices_menu(lang: str, server: str, protocol: str, months: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{d} устр.",
                callback_data=f"custom_devices:{server}:{protocol}:{months}:{d}",
            )
        ]
        for d in CUSTOM_DEVICE_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=f"custom_protocol:{server}:{protocol}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_menu(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"payment_{key}"), callback_data=f"payment:{key}")]
        for key in PAYMENT_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "payment_edit_connection"), callback_data="payment:edit_connection")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "summary_pay"), callback_data="pay:start", style="success")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
            [InlineKeyboardButton(text=tr(lang, "back_to_main"), callback_data="back:main")],
        ]
    )


def payment_simulation_menu(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "pay_success"), callback_data=f"pay:result:success:{order_id}", style="success")],
            [InlineKeyboardButton(text=tr(lang, "pay_failed"), callback_data=f"pay:result:failed:{order_id}", style="danger")],
            [InlineKeyboardButton(text=tr(lang, "pay_cancel"), callback_data=f"pay:result:cancel:{order_id}", style="danger")],
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
            [InlineKeyboardButton(text=tr(lang, "cryptobot_check_payment"), callback_data=f"pay:check:cryptobot:{order_id}:{invoice_id}", style="primary")],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="back:payment")],
        ]
    )


def server_node_menu(lang: str, country: str, nodes: list[tuple[str, int]], back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{node_id} (ping {ping})",
                callback_data=f"node:{country}:{node_id}",
            )
        ]
        for node_id, ping in nodes
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
