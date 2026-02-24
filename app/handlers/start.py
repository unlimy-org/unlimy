from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery

from app.db.repository import (
    ConnectionData,
    OrderData,
    Repository,
    ServerData,
    SupportTicketData,
    SupportTicketMessageData,
)
from app.keyboards.inline import (
    buy_menu,
    cryptobot_invoice_menu,
    custom_devices_menu,
    custom_months_menu,
    custom_protocol_menu,
    custom_server_menu,
    language_menu,
    main_menu,
    payment_done_menu,
    payment_menu,
    payment_retry_menu,
    payment_simulation_menu,
    ready_info_menu,
    ready_months_menu,
    ready_plan_menu,
    server_node_menu,
    support_menu,
    summary_menu,
)
from app.locales.translations import LANGUAGE_LABELS, tr
from app.services.catalog import (
    SERVER_KEYS,
    build_custom_plan_code,
    build_ready_plan_code,
    format_usd,
    get_ready_option,
    list_ready_options,
    list_ready_plans,
    parse_custom_plan_code,
    parse_ready_plan_code,
)
from app.services.cryptobot import CryptoBotClient, CryptoBotError
from app.services.master_node import MasterNodeClient, MasterNodeError
from app.services.ui import delete_last_bot_message, replace_bot_message

router = Router()
logger = logging.getLogger(__name__)
STATE_TICKET_CREATE = "ticket_create"
STATE_TICKET_REPLY = "ticket_reply"


@dataclass
class Offer:
    plan_code: str
    title: str
    usd: Decimal
    rub: int
    stars: int
    server: str
    protocol: str
    features: str
    months: int
    devices: int
    speed_limits: str
    data_limits: str


def _resolve_lang(user_lang: Optional[str], default_lang: str) -> str:
    if user_lang in LANGUAGE_LABELS:
        return user_lang
    if default_lang in LANGUAGE_LABELS:
        return default_lang
    return "en"


def _detect_initial_lang(tg_lang_code: Optional[str], default_lang: str) -> str:
    if tg_lang_code:
        base = tg_lang_code.lower().split("-", 1)[0]
        if base in LANGUAGE_LABELS:
            return base
    return _resolve_lang(default_lang, "en")


async def _get_user_lang(repo: Repository, tg_id: int, default_language: str) -> str:
    user = await repo.get_user(tg_id)
    if not user:
        return _resolve_lang(default_language, "en")
    return _resolve_lang(user.language, default_language)


def _protocol_label(protocol: str) -> str:
    if protocol == "wireguard":
        return "WireGuard"
    if protocol == "vless":
        return "VLESS"
    return protocol.title()


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q0(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _cfg_decimal(repo: Repository, key: str, default: Decimal) -> Decimal:
    raw = await repo.get_config_value(key)
    if raw is None:
        return default
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError):
        return default


async def _offer_from_plan(repo: Repository, plan_code: str) -> Optional[Offer]:
    usd_to_rub = await _cfg_decimal(repo, "pricing.usd_to_rub", Decimal("77"))
    usd_to_stars = await _cfg_decimal(repo, "pricing.usd_to_stars", Decimal("66.67"))

    ready = parse_ready_plan_code(plan_code)
    if ready:
        usd = await _cfg_decimal(repo, f"pricing.plan.{plan_code}.usd", ready.usd)
        rub = _q0(usd * usd_to_rub)
        stars = _q0(usd * usd_to_stars)
        return Offer(
            plan_code=plan_code,
            title=f"{ready.months} мес • {ready.plan_code.upper()}",
            usd=_q2(usd),
            rub=rub,
            stars=stars,
            server="auto",
            protocol="wireguard",
            features=ready.short_features,
            months=ready.months,
            devices=ready.devices,
            speed_limits=ready.speed,
            data_limits=ready.traffic,
        )

    custom = parse_custom_plan_code(plan_code)
    if custom:
        server, protocol, months, devices = custom
        # Configurable custom tariff formula with safe fallbacks.
        base_per_month = await _cfg_decimal(repo, "pricing.custom.base_usd_per_month", Decimal("3.00"))
        extra_device_per_month = await _cfg_decimal(repo, "pricing.custom.extra_device_usd_per_month", Decimal("0.90"))
        usd = _q2(base_per_month * Decimal(months) + extra_device_per_month * Decimal(max(devices - 1, 0)) * Decimal(months))
        rub = _q0(usd * usd_to_rub)
        stars = _q0(usd * usd_to_stars)
        return Offer(
            plan_code=plan_code,
            title=f"CUSTOM • {months} мес",
            usd=usd,
            rub=rub,
            stars=stars,
            server=server,
            protocol=protocol,
            features=f"{devices} устройств • Индивидуальный набор",
            months=months,
            devices=devices,
            speed_limits="custom",
            data_limits="custom",
        )
    return None


def _offer_text(lang: str, offer: Offer, payment_label: str = "-") -> str:
    return (
        f"{offer.title}\n"
        f"${format_usd(offer.usd)} • {offer.rub} ₽ • {offer.stars} ⭐\n"
        f"{offer.features}\n\n"
        f"Сервер: {tr(lang, f'server_{offer.server}') if offer.server in {'de','fi','no','nl','auto'} else offer.server}\n"
        f"Протокол: {_protocol_label(offer.protocol)}\n"
        f"Оплата: {payment_label}"
    )


def _ready_tariffs_details_text(lang: str) -> str:
    lines = [tr(lang, "ready_details_title"), ""]
    for plan in list_ready_plans():
        lines.append(f"{plan.badge} {plan.name}")
        lines.append(plan.description)
        for opt in list_ready_options(plan.code):
            lines.append(f"{opt.months} мес: ${format_usd(opt.usd)} • {opt.rub} ₽ • {opt.stars} ⭐")
        lines.append("")
    return "\n".join(lines).strip()


def _history_text(lang: str, orders: list[OrderData]) -> str:
    if not orders:
        return tr(lang, "orders_empty")
    lines = [tr(lang, "orders_title"), ""]
    for o in orders:
        lines.append(f"#{o.id} • {o.status} • ${o.amount_usd}")
        lines.append(f"{o.plan} | {o.server} | {_protocol_label(o.protocol)} | {o.payment_method}")
        lines.append("")
    return "\n".join(lines).strip()


def _connections_text(lang: str, conns: list[ConnectionData]) -> str:
    if not conns:
        return tr(lang, "connections_empty")
    lines = [tr(lang, "connections_title"), ""]
    for c in conns:
        lines.append(f"#{c.id} • {c.status} • {c.server_id} • {_protocol_label(c.protocol)}")
    return "\n".join(lines)


def _connections_menu(lang: str, conns: list[ConnectionData]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"#{c.id} {c.server_id} ({c.status})", callback_data=f"renew_pick:{c.id}")]
        for c in conns[:10]
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back_to_main"), callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _country_menu(lang: str, prefix: str, back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, f"server_{key}"), callback_data=f"{prefix}:{key}")]
        for key in SERVER_KEYS
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_admin(tg_id: int, support_admin_ids: set[int]) -> bool:
    return tg_id in support_admin_ids


def _ticket_status_label(lang: str, status: str) -> str:
    key = "support_status_open" if status == "open" else "support_status_closed"
    return tr(lang, key)


def _support_ticket_list_menu(lang: str, tickets: list[SupportTicketData], back_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"#{ticket.id} · {_ticket_status_label(lang, ticket.status)} · {ticket.tg_id}",
                callback_data=f"support:ticket:{ticket.id}",
            )
        ]
        for ticket in tickets[:15]
    ]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _support_ticket_view_menu(lang: str, ticket: SupportTicketData, is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=tr(lang, "support_reply_btn"), callback_data=f"support:reply:{ticket.id}")],
    ]
    if is_admin:
        if ticket.status == "open":
            rows.append([InlineKeyboardButton(text=tr(lang, "support_close_btn"), callback_data=f"support:status:{ticket.id}:closed")])
        else:
            rows.append([InlineKeyboardButton(text=tr(lang, "support_reopen_btn"), callback_data=f"support:status:{ticket.id}:open")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="menu:support")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _support_ticket_text(lang: str, ticket: SupportTicketData, messages: list[SupportTicketMessageData]) -> str:
    lines = [
        tr(lang, "support_ticket_title").format(ticket_id=ticket.id),
        f"{tr(lang, 'support_ticket_status')}: {_ticket_status_label(lang, ticket.status)}",
        "",
    ]
    if not messages:
        lines.append(tr(lang, "support_empty_messages"))
    else:
        for msg in messages[-12:]:
            role = tr(lang, "support_admin_label") if msg.is_admin else tr(lang, "support_user_label")
            lines.append(f"{role}: {msg.body}")
    lines.append("")
    lines.append(tr(lang, "support_send_hint"))
    return "\n".join(lines).strip()


async def _sync_servers(master_node_client: MasterNodeClient, repo: Repository) -> list[ServerData]:
    try:
        servers = await master_node_client.get_servers()
    except MasterNodeError:
        return []

    out: list[ServerData] = []
    for s in servers:
        row = ServerData(
            server_id=s.server_id,
            white_ip=s.white_ip,
            server_pwd="",
            country=s.country,
            ssh_key="",
            create_date="",
            status=s.status,
            stats=s.stats,
            ping_ms=s.ping_ms,
        )
        await repo.upsert_server_data(row)
        out.append(row)
    return out


async def _server_nodes_for_country(master_node_client: MasterNodeClient, repo: Repository, country: str) -> list[tuple[str, int]]:
    await _sync_servers(master_node_client, repo)
    rows = await repo.list_servers_by_country(country)
    if not rows:
        return []
    return [(r.server_id, r.ping_ms) for r in rows if r.status in {"up", "alive", "ok", "unknown"}]


def _expiry_iso(months: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=30 * max(months, 1))).isoformat()


async def _poll_master_task(
    bot,
    repo: Repository,
    master_node_client: MasterNodeClient,
    poll_interval_sec: int,
    tg_id: int,
    chat_id: int,
    connection_id: int,
    task_id: str,
    lang: str,
) -> None:
    logger.info(
        "config_poll_started tg_id=%s connection_id=%s task_id=%s interval=%s",
        tg_id,
        connection_id,
        task_id,
        poll_interval_sec,
    )
    for attempt in range(1, 41):
        try:
            status = await master_node_client.get_task_status(task_id)
        except MasterNodeError:
            status = None
            logger.exception(
                "config_poll_request_failed tg_id=%s connection_id=%s task_id=%s attempt=%s",
                tg_id,
                connection_id,
                task_id,
                attempt,
            )

        if status and status.status in {"done", "ready", "success"} and status.config_text:
            logger.info(
                "config_poll_ready tg_id=%s connection_id=%s task_id=%s attempt=%s config_len=%s",
                tg_id,
                connection_id,
                task_id,
                attempt,
                len(status.config_text),
            )
            await repo.update_connection_task(connection_id, tg_id, "active", task_id=task_id, config_text=status.config_text)
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=chat_id,
                tg_id=tg_id,
                text=status.config_text,
                reply_markup=payment_done_menu(lang),
            )
            return

        if status and status.status in {"failed", "error"}:
            logger.error(
                "config_poll_failed tg_id=%s connection_id=%s task_id=%s attempt=%s message=%s",
                tg_id,
                connection_id,
                task_id,
                attempt,
                status.message,
            )
            await repo.update_connection_task(connection_id, tg_id, "failed", task_id=task_id)
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=chat_id,
                tg_id=tg_id,
                text=tr(lang, "config_failed"),
                reply_markup=payment_done_menu(lang),
            )
            return

        logger.info(
            "config_poll_pending tg_id=%s connection_id=%s task_id=%s attempt=%s status=%s",
            tg_id,
            connection_id,
            task_id,
            attempt,
            status.status if status else "unknown",
        )
        await asyncio.sleep(max(5, poll_interval_sec))

    logger.error("config_poll_timeout tg_id=%s connection_id=%s task_id=%s", tg_id, connection_id, task_id)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=chat_id,
        tg_id=tg_id,
        text=tr(lang, "config_timeout"),
        reply_markup=payment_done_menu(lang),
    )


async def _start_config_build(
    *,
    bot,
    repo: Repository,
    master_node_client: MasterNodeClient,
    poll_interval_sec: int,
    tg_id: int,
    chat_id: int,
    order_id: int,
    offer: Offer,
    lang: str,
) -> None:
    logger.info(
        "config_create_started tg_id=%s order_id=%s server=%s protocol=%s",
        tg_id,
        order_id,
        offer.server,
        offer.protocol,
    )
    connection_id = await repo.create_connection(
        tg_id=tg_id,
        order_id=order_id,
        server_id=offer.server,
        protocol=offer.protocol,
        speed_limits=offer.speed_limits,
        devices_limits=str(offer.devices),
        data_limits=offer.data_limits,
        expiration_date=_expiry_iso(offer.months),
        status="pending",
    )

    payload = {
        "order_id": order_id,
        "connection_id": connection_id,
        "tg_id": tg_id,
        "plan": offer.plan_code,
        "server_id": offer.server,
        "protocol": offer.protocol,
    }

    try:
        created = await master_node_client.create_config(payload)
    except MasterNodeError:
        logger.exception(
            "config_create_master_error tg_id=%s order_id=%s connection_id=%s",
            tg_id,
            order_id,
            connection_id,
        )
        await repo.update_connection_task(connection_id, tg_id, "failed")
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=chat_id,
            tg_id=tg_id,
            text=tr(lang, "config_create_error"),
            reply_markup=payment_done_menu(lang),
        )
        return

    logger.info(
        "config_create_task_accepted tg_id=%s order_id=%s connection_id=%s task_id=%s",
        tg_id,
        order_id,
        connection_id,
        created.task_id,
    )
    await repo.update_connection_task(connection_id, tg_id, "creating", task_id=created.task_id)
    asyncio.create_task(
        _poll_master_task(
            bot=bot,
            repo=repo,
            master_node_client=master_node_client,
            poll_interval_sec=poll_interval_sec,
            tg_id=tg_id,
            chat_id=chat_id,
            connection_id=connection_id,
            task_id=created.task_id,
            lang=lang,
        )
    )


async def _complete_paid_order(
    *,
    call_or_msg,
    repo: Repository,
    bot,
    master_node_client: MasterNodeClient,
    poll_interval_sec: int,
    lang: str,
    order: OrderData,
) -> None:
    logger.info(
        "payment_completed tg_id=%s order_id=%s method=%s",
        order.tg_id,
        order.id,
        order.payment_method,
    )
    await repo.update_order_status(order.id, order.tg_id, "paid")
    await repo.log_payment_event(order.id, order.tg_id, order.payment_method, "succeeded", "payment_confirmed")

    offer = await _offer_from_plan(repo, order.plan)
    if not offer:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call_or_msg.chat.id if isinstance(call_or_msg, Message) else call_or_msg.message.chat.id,
            tg_id=order.tg_id,
            text=tr(lang, "pay_missing_draft"),
            reply_markup=main_menu(lang),
        )
        return

    offer.server = order.server
    offer.protocol = order.protocol

    chat_id = call_or_msg.chat.id if isinstance(call_or_msg, Message) else call_or_msg.message.chat.id
    await replace_bot_message(bot=bot, repo=repo, chat_id=chat_id, tg_id=order.tg_id, text=tr(lang, "config_starting"), reply_markup=payment_done_menu(lang))
    await repo.reset_draft(order.tg_id)

    await _start_config_build(
        bot=bot,
        repo=repo,
        master_node_client=master_node_client,
        poll_interval_sec=poll_interval_sec,
        tg_id=order.tg_id,
        chat_id=chat_id,
        order_id=order.id,
        offer=offer,
        lang=lang,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repository, default_language: str, bot):
    existing_user = await repo.get_user(message.from_user.id)
    username = message.from_user.username or ""
    full_name = " ".join(p for p in [message.from_user.first_name, message.from_user.last_name] if p).strip()
    if not existing_user:
        initial_lang = _detect_initial_lang(message.from_user.language_code, default_language)
        await repo.ensure_user(message.from_user.id, initial_lang, username=username, name=full_name)
        lang = initial_lang
    else:
        lang = _resolve_lang(existing_user.language, default_language)
        await repo.ensure_user(message.from_user.id, lang, username=username, name=full_name)

    await repo.reset_draft(message.from_user.id)
    await repo.clear_user_state(message.from_user.id)
    if existing_user:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except TelegramBadRequest:
            pass
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=message.chat.id,
        tg_id=message.from_user.id,
        text=tr(lang, "welcome"),
        reply_markup=main_menu(lang),
    )


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery, repo: Repository, default_language: str):
    lang = await _get_user_lang(repo, pre_checkout_query.from_user.id, default_language)
    payload = pre_checkout_query.invoice_payload or ""
    is_stars_order = payload.startswith("stars_order_") and pre_checkout_query.currency == "XTR"
    if is_stars_order:
        await pre_checkout_query.answer(ok=True)
        return
    await pre_checkout_query.answer(ok=False, error_message=tr(lang, "stars_precheckout_error"))


@router.message(F.successful_payment)
async def on_successful_stars_payment(
    message: Message,
    repo: Repository,
    default_language: str,
    master_node_client: MasterNodeClient,
    config_poll_interval_sec: int,
    bot,
):
    lang = await _get_user_lang(repo, message.from_user.id, default_language)
    payment = message.successful_payment
    payload = payment.invoice_payload or ""
    if not payload.startswith("stars_order_"):
        return

    try:
        order_id = int(payload.split("stars_order_", 1)[1])
    except ValueError:
        return

    order = await repo.get_order(order_id, message.from_user.id)
    if not order:
        return

    await repo.log_payment_event(order.id, order.tg_id, order.payment_method, "stars_payment_update", f"telegram_charge_id={payment.telegram_payment_charge_id}")
    await _complete_paid_order(
        call_or_msg=message,
        repo=repo,
        bot=bot,
        master_node_client=master_node_client,
        poll_interval_sec=config_poll_interval_sec,
        lang=lang,
        order=order,
    )


@router.message(F.text)
async def on_text_messages(message: Message, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    state, payload = await repo.get_user_state(message.from_user.id)
    if not state:
        return

    lang = await _get_user_lang(repo, message.from_user.id, default_language)
    chat_id = message.chat.id
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except TelegramBadRequest:
        pass

    if state == STATE_TICKET_CREATE:
        if not text:
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=chat_id,
                tg_id=message.from_user.id,
                text=tr(lang, "support_write_prompt"),
                reply_markup=support_menu(lang, _is_admin(message.from_user.id, support_admin_ids)),
            )
            return
        ticket_id = await repo.create_support_ticket(message.from_user.id, text[:2000])
        await repo.clear_user_state(message.from_user.id)
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=chat_id,
            tg_id=message.from_user.id,
            text=tr(lang, "support_created").format(ticket_id=ticket_id),
            reply_markup=support_menu(lang, _is_admin(message.from_user.id, support_admin_ids)),
        )
        for admin_id in support_admin_ids:
            if admin_id == message.from_user.id:
                continue
            try:
                await bot.send_message(
                    admin_id,
                    tr(lang, "support_admin_new_ticket").format(ticket_id=ticket_id, user_id=message.from_user.id),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=f"#{ticket_id}", callback_data=f"support:ticket:{ticket_id}")]]
                    ),
                )
            except TelegramBadRequest:
                continue
        return

    if state == STATE_TICKET_REPLY:
        if not payload or not payload.isdigit():
            await repo.clear_user_state(message.from_user.id)
            return
        ticket_id = int(payload)
        is_admin = _is_admin(message.from_user.id, support_admin_ids)
        ticket = await repo.get_support_ticket(ticket_id) if is_admin else await repo.get_support_ticket_for_user(ticket_id, message.from_user.id)
        if not ticket:
            await repo.clear_user_state(message.from_user.id)
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=chat_id,
                tg_id=message.from_user.id,
                text=tr(lang, "support_forbidden"),
                reply_markup=support_menu(lang, is_admin),
            )
            return
        await repo.add_support_ticket_message(ticket_id, message.from_user.id, text[:2000], is_admin=is_admin)
        await repo.clear_user_state(message.from_user.id)
        messages = await repo.list_support_ticket_messages(ticket_id, limit=20)
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=chat_id,
            tg_id=message.from_user.id,
            text=_support_ticket_text(lang, ticket, messages),
            reply_markup=_support_ticket_view_menu(lang, ticket, is_admin),
        )
        notify_targets = [ticket.tg_id] if is_admin else [aid for aid in support_admin_ids if aid != message.from_user.id]
        for target in notify_targets:
            try:
                await bot.send_message(
                    target,
                    tr(lang, "support_admin_new_reply").format(ticket_id=ticket_id),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=f"#{ticket_id}", callback_data=f"support:ticket:{ticket_id}")]]
                    ),
                )
            except TelegramBadRequest:
                continue


@router.callback_query(F.data == "menu:lang")
async def open_language_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "lang_title"), reply_markup=language_menu(lang))


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    code = call.data.split(":", 1)[1]
    lang = code if code in LANGUAGE_LABELS else _resolve_lang(default_language, "en")
    user = await repo.get_user(call.from_user.id)
    await repo.ensure_user(call.from_user.id, lang, username=(user.username if user else ""), name=(user.name if user else ""))
    await repo.set_language(call.from_user.id, lang)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "welcome"), reply_markup=main_menu(lang))


@router.callback_query(F.data == "menu:buy")
async def open_buy_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.reset_draft(call.from_user.id)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "buy_title"), reply_markup=buy_menu(lang))


@router.callback_query(F.data == "menu:orders")
async def open_orders_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    orders = await repo.list_orders_for_user(call.from_user.id, limit=15)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=_history_text(lang, orders),
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "menu:configs")
async def open_configs_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    conns = await repo.list_connections_for_user(call.from_user.id, limit=10)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=_connections_text(lang, conns),
        reply_markup=_connections_menu(lang, conns),
    )


@router.callback_query(F.data == "menu:support")
async def open_support_menu(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    is_admin = _is_admin(call.from_user.id, support_admin_ids)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "support_title"),
        reply_markup=support_menu(lang, is_admin),
    )


@router.callback_query(F.data == "info:terms")
async def open_terms(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    is_admin = _is_admin(call.from_user.id, support_admin_ids)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "info_terms_text"),
        reply_markup=support_menu(lang, is_admin),
    )


@router.callback_query(F.data == "info:privacy")
async def open_privacy(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    is_admin = _is_admin(call.from_user.id, support_admin_ids)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "info_privacy_text"),
        reply_markup=support_menu(lang, is_admin),
    )


@router.callback_query(F.data == "support:create")
async def support_create_ticket(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.set_user_state(call.from_user.id, STATE_TICKET_CREATE)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "support_write_prompt"),
        reply_markup=support_menu(lang, _is_admin(call.from_user.id, support_admin_ids)),
    )


@router.callback_query(F.data == "support:my")
async def support_my_tickets(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    tickets = await repo.list_support_tickets_for_user(call.from_user.id, limit=20)
    if not tickets:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "support_empty"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "back"), callback_data="menu:support")]]
            ),
        )
        return
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "support_my_title"),
        reply_markup=_support_ticket_list_menu(lang, tickets, back_callback="menu:support"),
    )


@router.callback_query(F.data == "support:open")
async def support_open_tickets(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    if not _is_admin(call.from_user.id, support_admin_ids):
        return
    await repo.clear_user_state(call.from_user.id)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    tickets = await repo.list_open_support_tickets(limit=30)
    if not tickets:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "support_open_empty"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "back"), callback_data="menu:support")]]
            ),
        )
        return
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "support_open_title"),
        reply_markup=_support_ticket_list_menu(lang, tickets, back_callback="menu:support"),
    )


@router.callback_query(F.data.startswith("support:ticket:"))
async def support_ticket_view(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    ticket_id_str = call.data.split(":")[-1]
    if not ticket_id_str.isdigit():
        return
    ticket_id = int(ticket_id_str)
    is_admin = _is_admin(call.from_user.id, support_admin_ids)
    ticket = await repo.get_support_ticket(ticket_id) if is_admin else await repo.get_support_ticket_for_user(ticket_id, call.from_user.id)
    if not ticket:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "support_forbidden"),
            reply_markup=support_menu(lang, is_admin),
        )
        return
    messages = await repo.list_support_ticket_messages(ticket.id, limit=30)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=_support_ticket_text(lang, ticket, messages),
        reply_markup=_support_ticket_view_menu(lang, ticket, is_admin),
    )


@router.callback_query(F.data.startswith("support:reply:"))
async def support_reply_ticket(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    ticket_id_str = call.data.split(":")[-1]
    if not ticket_id_str.isdigit():
        return
    ticket_id = int(ticket_id_str)
    is_admin = _is_admin(call.from_user.id, support_admin_ids)
    ticket = await repo.get_support_ticket(ticket_id) if is_admin else await repo.get_support_ticket_for_user(ticket_id, call.from_user.id)
    if not ticket:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "support_forbidden"),
            reply_markup=support_menu(lang, is_admin),
        )
        return
    if ticket.status != "open" and not is_admin:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "support_forbidden"),
            reply_markup=support_menu(lang, is_admin),
        )
        return
    await repo.set_user_state(call.from_user.id, STATE_TICKET_REPLY, payload=str(ticket_id))
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "support_reply_prompt").format(ticket_id=ticket_id),
        reply_markup=_support_ticket_view_menu(lang, ticket, is_admin),
    )


@router.callback_query(F.data.startswith("support:status:"))
async def support_update_ticket_status(call: CallbackQuery, repo: Repository, default_language: str, support_admin_ids: set[int], bot):
    await call.answer()
    if not _is_admin(call.from_user.id, support_admin_ids):
        return
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    parts = call.data.split(":")
    if len(parts) != 4 or not parts[2].isdigit():
        return
    ticket_id = int(parts[2])
    status = parts[3]
    if status not in {"open", "closed"}:
        return
    updated = await repo.update_support_ticket_status(ticket_id, status)
    if not updated:
        return
    ticket = await repo.get_support_ticket(ticket_id)
    if not ticket:
        return
    messages = await repo.list_support_ticket_messages(ticket.id, limit=30)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=_support_ticket_text(lang, ticket, messages),
        reply_markup=_support_ticket_view_menu(lang, ticket, True),
    )


@router.callback_query(F.data == "buy:ready")
async def open_ready_plans(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "ready_plan_title"), reply_markup=ready_plan_menu(lang))


@router.callback_query(F.data == "ready:info")
async def open_ready_tariffs_info(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=_ready_tariffs_details_text(lang), reply_markup=ready_info_menu(lang))


@router.callback_query(F.data.startswith("ready_plan:"))
async def choose_ready_plan(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    plan_code = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "ready_months_title"), reply_markup=ready_months_menu(lang, plan_code))


@router.callback_query(F.data.startswith("ready_month:"))
async def choose_ready_month(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    _, plan_code, months_str = call.data.split(":", 2)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    try:
        months = int(months_str)
    except ValueError:
        months = 1
    option = get_ready_option(plan_code, months)
    if not option:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_draft"), reply_markup=ready_plan_menu(lang))
        return

    plan = build_ready_plan_code(plan_code, months)
    await repo.upsert_draft(call.from_user.id, plan=plan, server="auto", protocol="wireguard")
    offer = await _offer_from_plan(repo, plan)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=_offer_text(lang, offer, payment_label=tr(lang, "payment_not_selected")), reply_markup=payment_menu(lang))


@router.callback_query(F.data == "buy:custom")
async def open_custom_country(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "custom_server_title"),
        reply_markup=custom_server_menu(lang),
    )


@router.callback_query(F.data.startswith("custom_server:"))
async def choose_custom_country(call: CallbackQuery, repo: Repository, default_language: str, master_node_client: MasterNodeClient, bot):
    await call.answer()
    country = call.data.split(":", 1)[1]
    if "|" in country:
        country = country.split("|", 1)[0]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    nodes = await _server_nodes_for_country(master_node_client, repo, country)
    if not nodes:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "servers_unavailable"), reply_markup=custom_server_menu(lang))
        return
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "custom_node_title"),
        reply_markup=server_node_menu(lang, country, nodes, back_callback="buy:custom"),
    )


@router.callback_query(F.data.startswith("node:"))
async def choose_server_node(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    _, country, node_id = call.data.split(":", 2)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "custom_protocol_title"),
        reply_markup=custom_protocol_menu(lang, f"{country}|{node_id}"),
    )


@router.callback_query(F.data.startswith("custom_protocol:"))
async def choose_custom_protocol(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    _, packed_server, protocol = call.data.split(":", 2)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "custom_months_title"),
        reply_markup=custom_months_menu(lang, packed_server, protocol),
    )


@router.callback_query(F.data.startswith("custom_month:"))
async def choose_custom_month(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    _, packed_server, protocol, months_str = call.data.split(":", 3)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    months = int(months_str)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "custom_devices_title"),
        reply_markup=custom_devices_menu(lang, packed_server, protocol, months),
    )


@router.callback_query(F.data.startswith("custom_devices:"))
async def choose_custom_devices(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    _, packed_server, protocol, months_str, devices_str = call.data.split(":", 4)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    months = int(months_str)
    devices = int(devices_str)

    if "|" in packed_server:
        _country, server_id = packed_server.split("|", 1)
    else:
        server_id = packed_server

    plan = build_custom_plan_code(server_id, protocol, months, devices)
    await repo.upsert_draft(call.from_user.id, plan=plan, server=server_id, protocol=protocol)
    offer = await _offer_from_plan(repo, plan)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=_offer_text(lang, offer, payment_label=tr(lang, "payment_not_selected")), reply_markup=payment_menu(lang))


@router.callback_query(F.data == "payment:edit_connection")
async def edit_connection_before_payment(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "edit_connection_title"),
        reply_markup=_country_menu(lang, prefix="edit_country", back_callback="back:payment"),
    )


@router.callback_query(F.data.startswith("edit_country:"))
async def edit_connection_country(call: CallbackQuery, repo: Repository, default_language: str, master_node_client: MasterNodeClient, bot):
    await call.answer()
    country = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    nodes = await _server_nodes_for_country(master_node_client, repo, country)
    if not nodes:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "servers_unavailable"), reply_markup=_country_menu(lang, prefix="edit_country", back_callback="back:payment"))
        return
    rows = [[InlineKeyboardButton(text=f"{node_id} (ping {ping})", callback_data=f"edit_node:{node_id}")] for node_id, ping in nodes]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="payment:edit_connection")])
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "select_server_node"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("edit_node:"))
async def edit_connection_node(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    node_id = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    draft = await repo.get_draft(call.from_user.id)
    protocol = draft.protocol or "wireguard"
    await repo.upsert_draft(call.from_user.id, server=node_id, protocol=protocol)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "connection_updated"), reply_markup=payment_menu(lang))


@router.callback_query(F.data.startswith("payment:"))
async def choose_payment(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    payment = call.data.split(":", 1)[1]
    if payment == "edit_connection":
        return
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.upsert_draft(call.from_user.id, payment=payment)
    draft = await repo.get_draft(call.from_user.id)

    if not draft.plan:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_draft"), reply_markup=buy_menu(lang))
        return

    offer = await _offer_from_plan(repo, draft.plan)
    if not offer:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_draft"), reply_markup=buy_menu(lang))
        return

    if draft.server:
        offer.server = draft.server
    if draft.protocol:
        offer.protocol = draft.protocol

    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=_offer_text(lang, offer, payment_label=tr(lang, f"payment_{payment}")),
        reply_markup=summary_menu(lang),
    )


@router.callback_query(F.data == "pay:start")
async def start_payment(
    call: CallbackQuery,
    repo: Repository,
    default_language: str,
    bot,
    stars_enabled: bool,
    cryptobot_enabled: bool,
    cryptobot_client: Optional[CryptoBotClient],
    cryptobot_asset: str,
):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    draft = await repo.get_draft(call.from_user.id)
    offer = await _offer_from_plan(repo, draft.plan or "")

    if not offer or not draft.payment:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_draft"), reply_markup=main_menu(lang))
        return

    if draft.server:
        offer.server = draft.server
    if draft.protocol:
        offer.protocol = draft.protocol

    await repo.upsert_draft(call.from_user.id, server=offer.server, protocol=offer.protocol)
    order_id = await repo.create_order_from_draft(tg_id=call.from_user.id, amount_usd=str(offer.usd))
    if order_id is None:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_draft"), reply_markup=main_menu(lang))
        return

    if draft.payment == "sbp":
        await repo.log_payment_event(order_id, call.from_user.id, draft.payment, "started", "local_stub_started")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_sim_title"), reply_markup=payment_simulation_menu(lang, order_id))
        return

    if draft.payment == "stars":
        if not stars_enabled:
            await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_unavailable"), reply_markup=payment_menu(lang))
            return

        await repo.log_payment_event(order_id, call.from_user.id, draft.payment, "started", f"stars_invoice_created amount={offer.stars}")
        await delete_last_bot_message(bot, repo, call.message.chat.id, call.from_user.id)
        invoice_message = await bot.send_invoice(
            chat_id=call.message.chat.id,
            title=tr(lang, "stars_invoice_title"),
            description=f"{offer.title} • ${format_usd(offer.usd)}",
            payload=f"stars_order_{order_id}",
            currency="XTR",
            prices=[LabeledPrice(label=offer.title, amount=offer.stars)],
        )
        await repo.set_last_bot_message_id(call.from_user.id, invoice_message.message_id)
        return

    if draft.payment == "cryptobot":
        if not cryptobot_enabled or cryptobot_client is None:
            await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_unavailable"), reply_markup=payment_menu(lang))
            return

        try:
            invoice = await cryptobot_client.create_invoice(
                amount=str(offer.usd),
                asset=cryptobot_asset,
                description=f"{offer.title} order #{order_id}",
                payload=f"order_{order_id}",
            )
        except CryptoBotError:
            await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_unavailable"), reply_markup=payment_menu(lang))
            return

        await repo.log_payment_event(order_id, call.from_user.id, draft.payment, "started", f"cryptobot_invoice_id={invoice.invoice_id}")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "cryptobot_invoice_text"), reply_markup=cryptobot_invoice_menu(lang, order_id, invoice.invoice_id, invoice.pay_url))
        return

    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_unavailable"), reply_markup=payment_menu(lang))


@router.callback_query(F.data.startswith("pay:check:cryptobot:"))
async def check_cryptobot_payment(
    call: CallbackQuery,
    repo: Repository,
    default_language: str,
    master_node_client: MasterNodeClient,
    config_poll_interval_sec: int,
    bot,
    cryptobot_enabled: bool,
    cryptobot_client: Optional[CryptoBotClient],
):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    parts = call.data.split(":")
    if len(parts) != 5:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    try:
        order_id = int(parts[3])
        invoice_id = int(parts[4])
    except ValueError:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    order = await repo.get_order(order_id, call.from_user.id)
    if not order or order.payment_method != "cryptobot":
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    if not cryptobot_enabled or cryptobot_client is None:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_unavailable"), reply_markup=payment_menu(lang))
        return

    try:
        invoice = await cryptobot_client.get_invoice(invoice_id)
    except CryptoBotError:
        invoice = None

    if not invoice:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=payment_menu(lang))
        return

    status = invoice.status.lower()
    if status == "paid":
        await repo.log_payment_event(order_id, call.from_user.id, "cryptobot", "cryptobot_paid", f"invoice_id={invoice_id}")
        await _complete_paid_order(
            call_or_msg=call,
            repo=repo,
            bot=bot,
            master_node_client=master_node_client,
            poll_interval_sec=config_poll_interval_sec,
            lang=lang,
            order=order,
        )
        return

    if status in {"expired", "cancelled"}:
        await repo.update_order_status(order_id, call.from_user.id, "failed", f"cryptobot_{status}")
        await repo.log_payment_event(order_id, call.from_user.id, "cryptobot", f"cryptobot_{status}", f"invoice_id={invoice_id}")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_failed_text").format(order_id=order_id), reply_markup=payment_retry_menu(lang))
        return

    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "cryptobot_pending"), reply_markup=cryptobot_invoice_menu(lang, order_id, invoice_id, invoice.pay_url))


@router.callback_query(F.data.startswith("pay:result:"))
async def finish_payment_simulation(
    call: CallbackQuery,
    repo: Repository,
    default_language: str,
    master_node_client: MasterNodeClient,
    config_poll_interval_sec: int,
    bot,
):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    parts = call.data.split(":")
    if len(parts) != 4:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    result = parts[2]
    try:
        order_id = int(parts[3])
    except ValueError:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    order = await repo.get_order(order_id, call.from_user.id)
    if not order:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    if result == "success":
        await repo.log_payment_event(order_id, call.from_user.id, order.payment_method, "stub_success", "local_stub_success")
        await _complete_paid_order(
            call_or_msg=call,
            repo=repo,
            bot=bot,
            master_node_client=master_node_client,
            poll_interval_sec=config_poll_interval_sec,
            lang=lang,
            order=order,
        )
    elif result == "failed":
        await repo.update_order_status(order_id, call.from_user.id, "failed", "local_stub_failure")
        await repo.log_payment_event(order_id, call.from_user.id, order.payment_method, "failed", "local_stub_failure")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_failed_text").format(order_id=order_id), reply_markup=payment_retry_menu(lang))
    elif result == "cancel":
        await repo.update_order_status(order_id, call.from_user.id, "cancelled", "local_stub_cancelled")
        await repo.log_payment_event(order_id, call.from_user.id, order.payment_method, "cancelled", "local_stub_cancelled")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_cancel_text").format(order_id=order_id), reply_markup=payment_retry_menu(lang))
    else:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))


@router.callback_query(F.data.startswith("renew_pick:"))
async def renew_pick_connection(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    conn_id = call.data.split(":", 1)[1]
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "renew_choose_country"),
        reply_markup=_country_menu(lang, prefix=f"renew_country:{conn_id}", back_callback="back:main"),
    )


@router.callback_query(F.data.startswith("renew_country:"))
async def renew_choose_country(call: CallbackQuery, repo: Repository, default_language: str, master_node_client: MasterNodeClient, bot):
    await call.answer()
    _, conn_id, country = call.data.split(":", 2)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    nodes = await _server_nodes_for_country(master_node_client, repo, country)
    if not nodes:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "servers_unavailable"), reply_markup=_country_menu(lang, prefix=f"renew_country:{conn_id}", back_callback="back:main"))
        return

    rows = [[InlineKeyboardButton(text=f"{node} (ping {ping})", callback_data=f"renew_node:{conn_id}:{node}")] for node, ping in nodes]
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data=f"renew_pick:{conn_id}")])
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "select_server_node"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("renew_node:"))
async def renew_node(call: CallbackQuery, repo: Repository, default_language: str, master_node_client: MasterNodeClient, config_poll_interval_sec: int, bot):
    await call.answer()
    _, conn_id_str, node_id = call.data.split(":", 2)
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    try:
        conn_id = int(conn_id_str)
    except ValueError:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "pay_missing_order"), reply_markup=main_menu(lang))
        return

    old_conn = await repo.get_connection(conn_id, call.from_user.id)
    if not old_conn:
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "connections_empty"), reply_markup=main_menu(lang))
        return

    new_conn_id = await repo.create_connection(
        tg_id=call.from_user.id,
        order_id=None,
        server_id=node_id,
        protocol=old_conn.protocol,
        speed_limits=old_conn.speed_limits,
        devices_limits=old_conn.devices_limits,
        data_limits=old_conn.data_limits,
        expiration_date=old_conn.expiration_date,
        status="pending",
    )
    payload = {
        "tg_id": call.from_user.id,
        "renew_of": old_conn.id,
        "connection_id": new_conn_id,
        "server_id": node_id,
        "protocol": old_conn.protocol,
    }

    try:
        created = await master_node_client.request_config_renew(payload)
    except MasterNodeError:
        await repo.update_connection_task(new_conn_id, call.from_user.id, "failed")
        await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "config_create_error"), reply_markup=main_menu(lang))
        return

    await repo.update_connection_task(new_conn_id, call.from_user.id, "creating", task_id=created.task_id)
    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=tr(lang, "renew_started"), reply_markup=main_menu(lang))
    asyncio.create_task(
        _poll_master_task(
            bot=bot,
            repo=repo,
            master_node_client=master_node_client,
            poll_interval_sec=config_poll_interval_sec,
            tg_id=call.from_user.id,
            chat_id=call.message.chat.id,
            connection_id=new_conn_id,
            task_id=created.task_id,
            lang=lang,
        )
    )


@router.callback_query(F.data.startswith("back:"))
async def on_back(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    await repo.clear_user_state(call.from_user.id)
    target = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)

    if target == "main":
        text = tr(lang, "welcome")
        kb = main_menu(lang)
    elif target == "buy":
        text = tr(lang, "buy_title")
        kb = buy_menu(lang)
    elif target == "payment":
        text = tr(lang, "payment_title")
        kb = payment_menu(lang)
    else:
        text = tr(lang, "welcome")
        kb = main_menu(lang)

    await replace_bot_message(bot=bot, repo=repo, chat_id=call.message.chat.id, tg_id=call.from_user.id, text=text, reply_markup=kb)
