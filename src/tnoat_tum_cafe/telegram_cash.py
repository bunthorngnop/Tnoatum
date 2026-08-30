from __future__ import annotations

from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from .models import User
from .services.auth import get_user_by_telegram_id
from .services.cash import cash_history, cash_status, record_cash_count, record_cash_movement, record_retained_float
from .services.money import format_money, parse_money


SELECT, AMOUNT, REASON, COUNT_KHR, COUNT_USD = range(5)


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌅 Opening Cash", callback_data="cash:OPENING_FLOAT")],
        [InlineKeyboardButton("💰 Cash Status", callback_data="cash:STATUS")],
        [InlineKeyboardButton("➕ Deposit", callback_data="cash:DEPOSIT"), InlineKeyboardButton("➖ Withdrawal", callback_data="cash:WITHDRAWAL")],
        [InlineKeyboardButton("👑 Owner Withdrawal", callback_data="cash:OWNER_WITHDRAWAL")],
        [InlineKeyboardButton("🔄 Adjustment", callback_data="cash:ADJUSTMENT")],
        [InlineKeyboardButton("🧮 Cash Count", callback_data="cash:COUNT"), InlineKeyboardButton("📜 Cash History", callback_data="cash:HISTORY")],
        [InlineKeyboardButton("🏦 Retained Float", callback_data="cash:RETAINED")],
    ])


async def _actor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    telegram_id = update.effective_user.id if update.effective_user else 0
    with context.application.bot_data["session_factory"]() as session:
        actor = get_user_by_telegram_id(session, telegram_id)
        return actor.id if actor else None


async def cash_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _actor(update, context) is None:
        await update.effective_message.reply_text("🔒 You are not authorized for this action.")
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("💵 CASH CONTROL\nKHR and USD stay separate. ABA/KHQR is shown separately.", reply_markup=_menu())
    else:
        await update.effective_message.reply_text("💵 CASH CONTROL\nKHR and USD stay separate. ABA/KHQR is shown separately.", reply_markup=_menu())
    return SELECT


async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    actor_id = await _actor(update, context)
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session:
            actor = session.get(User, actor_id)
            if action == "STATUS":
                status = cash_status(session, actor=actor)
                last = status.last_count
                text = ["💰 CASH STATUS", f"KHR expected: {format_money(status.expected_khr_minor, 'KHR')}", f"USD expected: {format_money(status.expected_usd_minor, 'USD')}"]
                if last:
                    text += [f"Last actual KHR: {format_money(last.actual_khr_minor, 'KHR')} | Difference: {format_money(last.difference_khr_minor, 'KHR')}", f"Last actual USD: {format_money(last.actual_usd_minor, 'USD')} | Difference: {format_money(last.difference_usd_minor, 'USD')}"]
                text += ["ABA/KHQR (not physical cash):", f"KHR: {format_money(status.aba_khr_minor, 'KHR')} | USD: {format_money(status.aba_usd_minor, 'USD')}"]
                await query.edit_message_text("\n".join(text), reply_markup=_menu())
                return SELECT
            if action == "HISTORY":
                rows = cash_history(session, actor=actor)
                text = ["📜 CASH HISTORY"] + [f"#{row.id} {row.movement_type} {row.direction} {format_money(row.amount_minor, row.currency)} — {row.reason}" for row in rows]
                await query.edit_message_text("\n".join(text) if rows else "📜 No cash movements yet.", reply_markup=_menu())
                return SELECT
    except (ValueError, PermissionError) as exc:
        await query.edit_message_text(f"⚠️ {exc}", reply_markup=_menu())
        return SELECT
    if action == "COUNT":
        context.user_data["cash_draft"] = {"action": action}
        await query.edit_message_text("🧮 Enter actual KHR cash (whole riel), or /cancel.")
        return COUNT_KHR
    context.user_data["cash_draft"] = {"action": action}
    await query.edit_message_text("Choose currency:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇰🇭 KHR", callback_data="cashcur:KHR"), InlineKeyboardButton("🇺🇸 USD", callback_data="cashcur:USD")]]))
    return SELECT


async def currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cash_draft"]["currency"] = query.data.split(":")[1]
    if context.user_data["cash_draft"]["action"] == "ADJUSTMENT":
        await query.edit_message_text("Adjustment direction:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Increase expected cash", callback_data="cashdir:INFLOW"), InlineKeyboardButton("➖ Decrease expected cash", callback_data="cashdir:OUTFLOW")]]))
        return SELECT
    await query.edit_message_text(f"Enter amount in {context.user_data['cash_draft']['currency']}, or /cancel.")
    return AMOUNT


async def adjustment_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["cash_draft"]["direction"] = query.data.split(":")[1]
    await query.edit_message_text(f"Enter adjustment amount in {context.user_data['cash_draft']['currency']}, or /cancel.")
    return AMOUNT


async def amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["cash_draft"]
    try:
        draft["amount_minor"] = parse_money(update.effective_message.text, draft["currency"])
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return AMOUNT
    await update.effective_message.reply_text("Enter the required reason, or /cancel.")
    return REASON


async def reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["cash_draft"]
    actor_id = await _actor(update, context)
    key = f"telegram-cash:{update.update_id}:{draft['action']}"
    try:
        with context.application.bot_data["session_factory"]() as session, session.begin():
            actor = session.get(User, actor_id)
            if draft["action"] == "RETAINED":
                record, created = record_retained_float(session, actor=actor, currency=draft["currency"], amount_minor=draft["amount_minor"], reason=update.effective_message.text, idempotency_key=key)
            else:
                direction = draft.get("direction") or ("INFLOW" if draft["action"] in {"OPENING_FLOAT", "DEPOSIT"} else "OUTFLOW")
                record, created = record_cash_movement(session, actor=actor, movement_type=draft["action"], direction=direction, amount_minor=draft["amount_minor"], currency=draft["currency"], reason=update.effective_message.text, idempotency_key=key)
        await update.effective_message.reply_text(f"✅ {'Recorded' if created else 'Already recorded'}: {format_money(record.amount_minor, record.currency)}", reply_markup=_menu())
    except (ValueError, PermissionError) as exc:
        await update.effective_message.reply_text(f"⚠️ Not recorded: {exc}", reply_markup=_menu())
    context.user_data.pop("cash_draft", None)
    return SELECT


async def count_khr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["cash_draft"]["actual_khr_minor"] = parse_money(update.effective_message.text, "KHR")
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return COUNT_KHR
    await update.effective_message.reply_text("Enter actual USD cash, or /cancel.")
    return COUNT_USD


async def count_usd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["cash_draft"]
    try:
        actual_usd = parse_money(update.effective_message.text, "USD")
        actor_id = await _actor(update, context)
        with context.application.bot_data["session_factory"]() as session, session.begin():
            actor = session.get(User, actor_id)
            count, created = record_cash_count(session, actor=actor, actual_khr_minor=draft["actual_khr_minor"], actual_usd_minor=actual_usd, idempotency_key=f"telegram-cash-count:{update.update_id}")
        await update.effective_message.reply_text(f"✅ {'Count recorded' if created else 'Count already recorded'}\nKHR difference: {format_money(count.difference_khr_minor, 'KHR')}\nUSD difference: {format_money(count.difference_usd_minor, 'USD')}\nBusiness day remains open.", reply_markup=_menu())
    except (ValueError, PermissionError) as exc:
        await update.effective_message.reply_text(f"⚠️ Count not recorded: {exc}", reply_markup=_menu())
    context.user_data.pop("cash_draft", None)
    return SELECT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("cash_draft", None)
    await update.effective_message.reply_text("Cancelled. Nothing was posted.", reply_markup=_menu())
    return SELECT


def build_cash_handler() -> ConversationHandler:
    return ConversationHandler(entry_points=[CommandHandler("cash", cash_start), CallbackQueryHandler(cash_start, pattern=r"^main:cash$")], states={SELECT: [CallbackQueryHandler(choose, pattern=r"^cash:"), CallbackQueryHandler(currency, pattern=r"^cashcur:(KHR|USD)$"), CallbackQueryHandler(adjustment_direction, pattern=r"^cashdir:(INFLOW|OUTFLOW)$")], AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount)], REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, reason)], COUNT_KHR: [MessageHandler(filters.TEXT & ~filters.COMMAND, count_khr)], COUNT_USD: [MessageHandler(filters.TEXT & ~filters.COMMAND, count_usd)]}, fallbacks=[CommandHandler("cancel", cancel)], allow_reentry=True)
