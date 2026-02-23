from typing import Optional

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from app.db.repository import OrderData, Repository
from app.keyboards.inline import (
    cryptobot_invoice_menu,
    language_menu,
    main_menu,
    payment_done_menu,
    payment_menu,
    payment_retry_menu,
    payment_simulation_menu,
    plan_menu,
    protocol_menu,
    server_menu,
    summary_menu,
)
from app.locales.translations import LANGUAGE_LABELS, tr
from app.services.catalog import PLAN_PRICES_STARS, PLAN_PRICES_USD
from app.services.cryptobot import CryptoBotClient, CryptoBotError
from app.services.provisioning import ProvisioningResult, ProvisioningService
from app.services.ui import delete_last_bot_message, replace_bot_message

router = Router()


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


def _purchase_text(lang: str, order: OrderData) -> str:
    return tr(lang, "purchase_success_body").format(
        order_id=order.id,
        plan=tr(lang, f"plan_{order.plan}"),
        server=tr(lang, f"server_{order.server}"),
        protocol=_protocol_label(order.protocol),
        payment=tr(lang, f"payment_{order.payment_method}"),
    )


async def _mark_paid_and_respond(
    call_or_msg,
    repo: Repository,
    provisioning_service: ProvisioningService,
    bot,
    lang: str,
    order: OrderData,
) -> None:
    await repo.update_order_status(order.id, order.tg_id, "paid")
    await repo.log_payment_event(
        order_id=order.id,
        tg_id=order.tg_id,
        payment_method=order.payment_method,
        event_type="succeeded",
        details="payment_confirmed",
    )
    await repo.reset_draft(order.tg_id)
    provision: ProvisioningResult = await provisioning_service.enqueue_after_payment(order)

    chat_id = call_or_msg.chat.id if isinstance(call_or_msg, Message) else call_or_msg.message.chat.id
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=chat_id,
        tg_id=order.tg_id,
        text=(
            f"{tr(lang, 'purchase_success_title')}\n\n{_purchase_text(lang, order)}\n\n"
            + tr(lang, "provisioning_stub_info").format(
                job_id=provision.job_id,
                node=provision.slave_node,
                status=provision.status,
            )
        ),
        reply_markup=payment_done_menu(lang),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repository, default_language: str, bot):
    existing_user = await repo.get_user(message.from_user.id)
    if not existing_user:
        initial_lang = _detect_initial_lang(message.from_user.language_code, default_language)
        await repo.ensure_user(message.from_user.id, initial_lang)
        lang = initial_lang
    else:
        lang = _resolve_lang(existing_user.language, default_language)

    await repo.reset_draft(message.from_user.id)
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
    provisioning_service: ProvisioningService,
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

    await repo.log_payment_event(
        order_id=order.id,
        tg_id=order.tg_id,
        payment_method=order.payment_method,
        event_type="stars_payment_update",
        details=f"telegram_charge_id={payment.telegram_payment_charge_id}",
    )
    await _mark_paid_and_respond(message, repo, provisioning_service, bot, lang, order)


@router.message(F.text)
async def ignore_text_messages(_: Message):
    return


@router.callback_query(F.data == "menu:lang")
async def open_language_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "lang_title"),
        reply_markup=language_menu(lang),
    )


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    code = call.data.split(":", 1)[1]
    lang = code if code in LANGUAGE_LABELS else _resolve_lang(default_language, "en")
    await repo.ensure_user(call.from_user.id, lang)
    await repo.set_language(call.from_user.id, lang)

    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "welcome"),
        reply_markup=main_menu(lang),
    )


@router.callback_query(F.data == "menu:buy")
async def open_plan_menu(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.reset_draft(call.from_user.id)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "plan_title"),
        reply_markup=plan_menu(lang),
    )


@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    plan = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.upsert_draft(call.from_user.id, plan=plan)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "server_title"),
        reply_markup=server_menu(lang),
    )


@router.callback_query(F.data.startswith("server:"))
async def choose_server(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    server = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.upsert_draft(call.from_user.id, server=server)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "protocol_title"),
        reply_markup=protocol_menu(lang),
    )


@router.callback_query(F.data.startswith("protocol:"))
async def choose_protocol(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    protocol = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.upsert_draft(call.from_user.id, protocol=protocol)
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "payment_title"),
        reply_markup=payment_menu(lang),
    )


@router.callback_query(F.data.startswith("payment:"))
async def choose_payment(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    payment = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)
    await repo.upsert_draft(call.from_user.id, payment=payment)
    draft = await repo.get_draft(call.from_user.id)

    summary_text = tr(lang, "summary").format(
        plan=tr(lang, f"plan_{draft.plan}"),
        server=tr(lang, f"server_{draft.server}"),
        protocol=_protocol_label(draft.protocol or ""),
        payment=tr(lang, f"payment_{draft.payment}"),
    )
    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=summary_text,
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

    if not draft.plan or draft.plan not in PLAN_PRICES_USD or not draft.payment:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_draft"),
            reply_markup=main_menu(lang),
        )
        return

    order_id = await repo.create_order_from_draft(
        tg_id=call.from_user.id,
        amount_usd=PLAN_PRICES_USD[draft.plan],
    )
    if order_id is None:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_draft"),
            reply_markup=main_menu(lang),
        )
        return

    if draft.payment == "sbp":
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=draft.payment,
            event_type="started",
            details="local_stub_started",
        )
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_sim_title"),
            reply_markup=payment_simulation_menu(lang, order_id),
        )
        return

    if draft.payment == "stars":
        if not stars_enabled:
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=call.message.chat.id,
                tg_id=call.from_user.id,
                text=tr(lang, "pay_unavailable"),
                reply_markup=payment_menu(lang),
            )
            return

        stars_amount = PLAN_PRICES_STARS.get(draft.plan)
        if not stars_amount:
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=call.message.chat.id,
                tg_id=call.from_user.id,
                text=tr(lang, "pay_missing_draft"),
                reply_markup=payment_menu(lang),
            )
            return

        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=draft.payment,
            event_type="started",
            details=f"stars_invoice_created amount={stars_amount}",
        )

        await delete_last_bot_message(bot, repo, call.message.chat.id, call.from_user.id)
        invoice_message = await bot.send_invoice(
            chat_id=call.message.chat.id,
            title=tr(lang, "stars_invoice_title"),
            description=tr(lang, "stars_invoice_description"),
            payload=f"stars_order_{order_id}",
            currency="XTR",
            prices=[LabeledPrice(label=tr(lang, f"plan_{draft.plan}"), amount=stars_amount)],
        )
        await repo.set_last_bot_message_id(call.from_user.id, invoice_message.message_id)
        return

    if draft.payment == "cryptobot":
        if not cryptobot_enabled or cryptobot_client is None:
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=call.message.chat.id,
                tg_id=call.from_user.id,
                text=tr(lang, "pay_unavailable"),
                reply_markup=payment_menu(lang),
            )
            return

        amount = PLAN_PRICES_USD[draft.plan]
        try:
            invoice = await cryptobot_client.create_invoice(
                amount=str(amount),
                asset=cryptobot_asset,
                description=f"VPN plan {draft.plan} order #{order_id}",
                payload=f"order_{order_id}",
            )
        except CryptoBotError:
            await replace_bot_message(
                bot=bot,
                repo=repo,
                chat_id=call.message.chat.id,
                tg_id=call.from_user.id,
                text=tr(lang, "pay_unavailable"),
                reply_markup=payment_menu(lang),
            )
            return

        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=draft.payment,
            event_type="started",
            details=f"cryptobot_invoice_id={invoice.invoice_id}",
        )
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "cryptobot_invoice_text"),
            reply_markup=cryptobot_invoice_menu(lang, order_id, invoice.invoice_id, invoice.pay_url),
        )
        return

    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "pay_unavailable"),
        reply_markup=payment_menu(lang),
    )


@router.callback_query(F.data.startswith("pay:check:cryptobot:"))
async def check_cryptobot_payment(
    call: CallbackQuery,
    repo: Repository,
    default_language: str,
    provisioning_service: ProvisioningService,
    bot,
    cryptobot_enabled: bool,
    cryptobot_client: Optional[CryptoBotClient],
):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)

    parts = call.data.split(":")
    if len(parts) != 5:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    try:
        order_id = int(parts[3])
        invoice_id = int(parts[4])
    except ValueError:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    order = await repo.get_order(order_id, call.from_user.id)
    if not order or order.payment_method != "cryptobot":
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    if not cryptobot_enabled or cryptobot_client is None:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_unavailable"),
            reply_markup=payment_menu(lang),
        )
        return

    try:
        invoice = await cryptobot_client.get_invoice(invoice_id)
    except CryptoBotError:
        invoice = None

    if not invoice:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=payment_menu(lang),
        )
        return

    status = invoice.status.lower()
    if status == "paid":
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method="cryptobot",
            event_type="cryptobot_paid",
            details=f"invoice_id={invoice_id}",
        )
        await _mark_paid_and_respond(call, repo, provisioning_service, bot, lang, order)
        return

    if status in {"expired", "cancelled"}:
        await repo.update_order_status(
            order_id,
            call.from_user.id,
            "failed",
            failure_reason=f"cryptobot_{status}",
        )
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method="cryptobot",
            event_type=f"cryptobot_{status}",
            details=f"invoice_id={invoice_id}",
        )
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_failed_text").format(order_id=order_id),
            reply_markup=payment_retry_menu(lang),
        )
        return

    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=tr(lang, "cryptobot_pending"),
        reply_markup=cryptobot_invoice_menu(lang, order_id, invoice_id, invoice.pay_url),
    )


@router.callback_query(F.data.startswith("pay:result:"))
async def finish_payment_simulation(
    call: CallbackQuery,
    repo: Repository,
    default_language: str,
    provisioning_service: ProvisioningService,
    bot,
):
    await call.answer()
    lang = await _get_user_lang(repo, call.from_user.id, default_language)

    parts = call.data.split(":")
    if len(parts) != 4:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    result = parts[2]
    try:
        order_id = int(parts[3])
    except ValueError:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    order = await repo.get_order(order_id, call.from_user.id)
    if not order:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )
        return

    if result == "success":
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=order.payment_method,
            event_type="stub_success",
            details="local_stub_success",
        )
        await _mark_paid_and_respond(call, repo, provisioning_service, bot, lang, order)
    elif result == "failed":
        await repo.update_order_status(
            order_id,
            call.from_user.id,
            "failed",
            failure_reason="local_stub_failure",
        )
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=order.payment_method,
            event_type="failed",
            details="local_stub_failure",
        )
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_failed_text").format(order_id=order_id),
            reply_markup=payment_retry_menu(lang),
        )
    elif result == "cancel":
        await repo.update_order_status(
            order_id,
            call.from_user.id,
            "cancelled",
            failure_reason="local_stub_cancelled",
        )
        await repo.log_payment_event(
            order_id=order_id,
            tg_id=call.from_user.id,
            payment_method=order.payment_method,
            event_type="cancelled",
            details="local_stub_cancelled",
        )
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_cancel_text").format(order_id=order_id),
            reply_markup=payment_retry_menu(lang),
        )
    else:
        await replace_bot_message(
            bot=bot,
            repo=repo,
            chat_id=call.message.chat.id,
            tg_id=call.from_user.id,
            text=tr(lang, "pay_missing_order"),
            reply_markup=main_menu(lang),
        )


@router.callback_query(F.data.startswith("back:"))
async def on_back(call: CallbackQuery, repo: Repository, default_language: str, bot):
    await call.answer()
    target = call.data.split(":", 1)[1]
    lang = await _get_user_lang(repo, call.from_user.id, default_language)

    if target == "main":
        text = tr(lang, "welcome")
        kb = main_menu(lang)
    elif target == "plan":
        text = tr(lang, "plan_title")
        kb = plan_menu(lang)
    elif target == "server":
        text = tr(lang, "server_title")
        kb = server_menu(lang)
    elif target == "protocol":
        text = tr(lang, "protocol_title")
        kb = protocol_menu(lang)
    elif target == "payment":
        text = tr(lang, "payment_title")
        kb = payment_menu(lang)
    else:
        text = tr(lang, "welcome")
        kb = main_menu(lang)

    await replace_bot_message(
        bot=bot,
        repo=repo,
        chat_id=call.message.chat.id,
        tg_id=call.from_user.id,
        text=text,
        reply_markup=kb,
    )
