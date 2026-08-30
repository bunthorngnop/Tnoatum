from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from .config import PROJECT_ROOT
from .models import ExpenseCategory, ExpenseRequest, ExpenseRequestStatus, NotificationOutbox, User, utc_now
from .services.auth import get_user_by_telegram_id, has_permission
from .services.business_days import active_business_day
from .services.expenses import AttachmentInput, approve_expense_request, ask_expense_question, expense_activity, record_expense_approval_opened, reject_expense_request, respond_to_expense_question, submit_expense_request
from .services.money import format_money, parse_money
from . import strings


CATEGORY, AMOUNT, REASON, RECEIPT, DECISION_REASON = range(20, 25)
logger = logging.getLogger(__name__)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(strings.NEW_SALE, callback_data="main:new")],
        [InlineKeyboardButton(strings.NEW_EXPENSE, callback_data="main:expense")],
        [InlineKeyboardButton(strings.MY_ACCOUNT, callback_data="main:account")],
        [InlineKeyboardButton(strings.MY_EXPENSES, callback_data="main:myexpenses"), InlineKeyboardButton(strings.PENDING_APPROVALS, callback_data="main:approvals")],
    ])


async def _actor_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    telegram_id = update.effective_user.id if update.effective_user else 0
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = get_user_by_telegram_id(session, telegram_id)
        if actor is not None:
            return actor.id
    if update.callback_query:
        await update.callback_query.answer(strings.UNAUTHORIZED, show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(strings.UNAUTHORIZED)
    return None


async def begin_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = session.get(User, actor_id)
        if not has_permission(session, actor, "expense.create"):
            await update.effective_message.reply_text(strings.UNAUTHORIZED)
            return ConversationHandler.END
        if active_business_day(session) is None:
            await update.effective_message.reply_text(strings.NO_BUSINESS_DAY, reply_markup=_main_keyboard())
            return ConversationHandler.END
        categories = list(session.scalars(select(ExpenseCategory).where(ExpenseCategory.is_active.is_(True)).order_by(ExpenseCategory.sort_order, ExpenseCategory.name)))
    context.user_data["expense_draft"] = {}
    keyboard = [[InlineKeyboardButton(f"{category.icon or '📦'} {category.name}", callback_data=f"expcat:{category.id}")] for category in categories]
    keyboard.append([InlineKeyboardButton(strings.CANCEL, callback_data="expcancel")])
    message = "💸 New Expense — select category / ជ្រើសប្រភេទចំណាយ៖"
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.effective_message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    return CATEGORY


async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["expense_draft"]["category_id"] = int(query.data.split(":")[1])
    await query.edit_message_text("Choose currency:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇰🇭 KHR", callback_data="expcur:KHR"), InlineKeyboardButton("🇺🇸 USD", callback_data="expcur:USD")]]))
    return CATEGORY


async def choose_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    currency = query.data.split(":")[1]
    context.user_data["expense_draft"]["currency"] = currency
    await query.edit_message_text(f"Enter exact amount in {currency} (whole riel for KHR; up to 2 decimals for USD):")
    return AMOUNT


async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data["expense_draft"]
    try:
        draft["amount_minor"] = parse_money(update.effective_message.text, draft["currency"])
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}. Try again or /cancel.")
        return AMOUNT
    cash_source = f"{draft['currency']}_CASH"
    await update.effective_message.reply_text("Select payment source:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💵 {draft['currency']} Cash", callback_data=f"expsrc:{cash_source}")], [InlineKeyboardButton("📱 ABA/KHQR", callback_data="expsrc:ABA_KHQR")]]))
    return CATEGORY


async def choose_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["expense_draft"]["payment_source"] = query.data.split(":")[1]
    await query.edit_message_text("Enter reason/description (required, maximum 1,000 characters):")
    return REASON


async def enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.effective_message.text.strip()
    if not reason or len(reason) > 1000:
        await update.effective_message.reply_text("Reason must contain 1–1,000 characters.")
        return REASON
    context.user_data["expense_draft"]["reason"] = reason
    settings = context.application.bot_data["settings"]
    draft = context.user_data["expense_draft"]
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        category = session.get(ExpenseCategory, draft["category_id"])
        required = settings.require_receipt_for_all_expenses or category.receipt_required
    draft["receipt_required"] = required
    keyboard = [[InlineKeyboardButton("📷 Add Receipt", callback_data="expreceipt:add")]]
    if not required:
        keyboard.append([InlineKeyboardButton("Skip Receipt", callback_data="expreceipt:skip")])
    await update.effective_message.reply_text("Receipt required." if required else "Add a receipt, or skip if permitted:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CATEGORY


async def receipt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    draft = context.user_data["expense_draft"]
    if action == "skip":
        if draft.get("receipt_required"):
            await query.answer("Receipt is required", show_alert=True)
            return CATEGORY
        draft["attachments"] = []
        return await _show_review(query, context)
    await query.edit_message_text("Send one receipt as a Telegram photo or document (maximum configured size), or /cancel.")
    return RECEIPT


def _attachment_path(settings, mime_type: str | None) -> tuple[Path, str]:
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}.get(mime_type, ".bin")
    relative = Path(settings.expense_attachment_directory) / f"{uuid4().hex}{suffix}"
    absolute = relative if relative.is_absolute() else PROJECT_ROOT / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    return absolute, relative.as_posix()


async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    settings = context.application.bot_data["settings"]
    if message.photo:
        media = message.photo[-1]
        file_id, unique_id, size, media_type, mime_type = media.file_id, media.file_unique_id, media.file_size, "PHOTO", "image/jpeg"
    elif message.document:
        media = message.document
        file_id, unique_id, size, media_type, mime_type = media.file_id, media.file_unique_id, media.file_size, "DOCUMENT", media.mime_type
    else:
        await message.reply_text("Send a photo or document receipt.")
        return RECEIPT
    if size is not None and size > settings.max_expense_attachment_bytes:
        await message.reply_text("Receipt file is larger than the configured limit.")
        return RECEIPT
    absolute, relative = _attachment_path(settings, mime_type)
    telegram_file = await context.bot.get_file(file_id)
    await telegram_file.download_to_drive(custom_path=absolute)
    context.user_data["expense_draft"]["attachments"] = [{"telegram_file_id": file_id, "telegram_file_unique_id": unique_id, "media_type": media_type, "mime_type": mime_type, "file_size": size, "local_relative_path": relative}]
    token = uuid4().hex[:16]
    context.user_data["expense_draft"]["confirm_token"] = token
    await message.reply_text(_review_text(context.user_data["expense_draft"]), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit Expense", callback_data=f"expconfirm:{token}")], [InlineKeyboardButton(strings.CANCEL, callback_data="expcancel")]]))
    return CATEGORY


def _review_text(draft: dict) -> str:
    return (f"💸 EXPENSE REVIEW\nAmount: {format_money(draft['amount_minor'], draft['currency'])}\nPayment: {draft['payment_source']}\nReason: {draft['reason']}\nReceipt: {'YES' if draft.get('attachments') else 'NO'}\n\nNo ledger posting occurs until submitted and authorized.")


async def _show_review(query, context) -> int:
    draft = context.user_data["expense_draft"]
    token = uuid4().hex[:16]
    draft["confirm_token"] = token
    await query.edit_message_text(_review_text(draft), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit Expense", callback_data=f"expconfirm:{token}")], [InlineKeyboardButton(strings.CANCEL, callback_data="expcancel")]]))
    return CATEGORY


async def confirm_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    draft = context.user_data.get("expense_draft", {})
    token = query.data.split(":")[1]
    if token != draft.get("confirm_token"):
        await query.answer("Stale confirmation", show_alert=True)
        return ConversationHandler.END
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    settings = context.application.bot_data["settings"]
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            result = submit_expense_request(session, actor=actor, category_id=draft["category_id"], amount_minor=draft["amount_minor"], currency=draft["currency"], payment_source=draft["payment_source"], reason=draft["reason"], attachments=[AttachmentInput(**item) for item in draft.get("attachments", [])], idempotency_key=f"telegram-expense:{token}", within_limit_posts_immediately=settings.expense_within_limit_posts_immediately, require_receipt_for_all=settings.require_receipt_for_all_expenses)
            number, status, posted = result.request.request_number, result.request.status, result.expense is not None
    except (ValueError, PermissionError) as exc:
        await query.edit_message_text(f"⚠️ Expense not submitted: {exc}", reply_markup=_main_keyboard())
        return ConversationHandler.END
    context.user_data.pop("expense_draft", None)
    await query.edit_message_text(f"{'✅ POSTED' if posted else '⏳ PENDING APPROVAL'}\nRequest: {number}\nStatus: {status}", reply_markup=_main_keyboard())
    await dispatch_notifications(context)
    return ConversationHandler.END


async def cancel_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("expense_draft", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Expense cancelled safely. No request or ledger entry was posted.", reply_markup=_main_keyboard())
    else:
        await update.effective_message.reply_text("Expense cancelled safely.", reply_markup=_main_keyboard())
    return ConversationHandler.END


async def my_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = session.get(User, actor_id)
        requests = expense_activity(session, requester=actor, limit=10)
        lines = [strings.MY_EXPENSES]
        lines.extend(f"{item.request_number} • {format_money(item.amount_minor, item.currency)} • {item.status}" for item in requests)
    if len(lines) == 1:
        lines.append("No expense activity yet.")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=_main_keyboard())
    return ConversationHandler.END


async def pending_approvals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = session.get(User, actor_id)
        if not has_permission(session, actor, "expense.approve"):
            await update.effective_message.reply_text(strings.UNAUTHORIZED)
            return ConversationHandler.END
        requests = list(session.scalars(select(ExpenseRequest).where(ExpenseRequest.status == ExpenseRequestStatus.PENDING.value).order_by(ExpenseRequest.submitted_at).limit(20)))
    if not requests:
        await update.effective_message.reply_text("✅ No pending expense approvals.", reply_markup=_main_keyboard())
        return ConversationHandler.END
    await update.effective_message.reply_text(f"⏳ {len(requests)} pending expense request(s):")
    for request in requests:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVE", callback_data=f"expapprove:{request.id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"expreject:{request.id}")], [InlineKeyboardButton("💬 ASK QUESTION", callback_data=f"expquestion:{request.id}")]])
        await update.effective_message.reply_text(f"{request.request_number}\n{format_money(request.amount_minor, request.currency)} • {request.payment_source}\n{request.reason}", reply_markup=keyboard)
    return ConversationHandler.END


async def approval_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    action, raw_id = query.data.split(":")
    request_id = int(raw_id)
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            record_expense_approval_opened(session, actor=actor, request_id=request_id, idempotency_key=f"telegram-opened:{query.id}")
    except (ValueError, PermissionError) as exc:
        await query.edit_message_text(f"⚠️ Approval unavailable: {exc}")
        return ConversationHandler.END
    if action == "expapprove":
        try:
            with factory() as session, session.begin():
                actor = session.get(User, actor_id)
                expense, created = approve_expense_request(session, actor=actor, request_id=request_id, idempotency_key=f"telegram-approve:{query.id}")
                number = expense.expense_number
        except (ValueError, PermissionError) as exc:
            await query.edit_message_text(f"⚠️ Approval not applied: {exc}")
            return ConversationHandler.END
        await query.edit_message_text(f"✅ {'APPROVED' if created else 'ALREADY APPROVED'}\nExpense: {number}")
        await dispatch_notifications(context)
        return ConversationHandler.END
    context.user_data["expense_decision"] = {"request_id": request_id, "action": action}
    prompt = "Enter rejection reason:" if action == "expreject" else "Enter your question for the requester:"
    await query.edit_message_text(prompt)
    return DECISION_REASON


async def decision_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return ConversationHandler.END
    decision = context.user_data.pop("expense_decision", None)
    if not decision:
        await update.effective_message.reply_text("Decision context expired. Open approvals again.")
        return ConversationHandler.END
    text = update.effective_message.text.strip()
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            key = f"telegram-{decision['action']}:{update.update_id}"
            if decision["action"] == "expreject":
                request, created = reject_expense_request(session, actor=actor, request_id=decision["request_id"], reason=text, idempotency_key=key)
                message = f"❌ {'REJECTED' if created else 'ALREADY REJECTED'} {request.request_number}"
            else:
                request, created = ask_expense_question(session, actor=actor, request_id=decision["request_id"], question=text, idempotency_key=key)
                message = f"💬 Question {'sent' if created else 'already recorded'} for {request.request_number}; status remains PENDING."
    except (ValueError, PermissionError) as exc:
        await update.effective_message.reply_text(f"⚠️ Decision not applied: {exc}")
        return ConversationHandler.END
    await update.effective_message.reply_text(message, reply_markup=_main_keyboard())
    await dispatch_notifications(context)
    return ConversationHandler.END


async def expense_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    actor_id = await _actor_id(update, context)
    if actor_id is None:
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /expense_reply REQUEST_ID your response")
        return
    try:
        request_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("REQUEST_ID must be numeric.")
        return
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            request, created = respond_to_expense_question(session, actor=actor, request_id=request_id, response=" ".join(context.args[1:]), idempotency_key=f"telegram-response:{update.update_id}")
    except (ValueError, PermissionError) as exc:
        await update.effective_message.reply_text(f"⚠️ Response not recorded: {exc}")
        return
    await update.effective_message.reply_text(f"💬 Response {'sent' if created else 'already recorded'} for {request.request_number}.")
    await dispatch_notifications(context)


async def dispatch_notifications(context: ContextTypes.DEFAULT_TYPE) -> None:
    await dispatch_notification_outbox(context.application)


async def dispatch_notification_outbox(application) -> None:
    factory = application.bot_data["session_factory"]
    with factory() as session:
        notifications = list(session.scalars(select(NotificationOutbox).where(NotificationOutbox.sent_at.is_(None)).order_by(NotificationOutbox.id).limit(100)))
        for notification in notifications:
            recipient = session.get(User, notification.recipient_user_id)
            keyboard = None
            if notification.notification_type == "EXPENSE_APPROVAL_REQUEST":
                request_id = int(notification.entity_id)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVE", callback_data=f"expapprove:{request_id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"expreject:{request_id}")], [InlineKeyboardButton("💬 ASK QUESTION", callback_data=f"expquestion:{request_id}")]])
            try:
                await application.bot.send_message(chat_id=recipient.telegram_user_id, text=notification.message, reply_markup=keyboard)
                notification.sent_at = utc_now()
            except Exception as exc:
                notification.attempts += 1
                logger.warning("Notification %s delivery failed: %s", notification.id, type(exc).__name__)
        session.commit()


async def startup_notification_dispatch(application) -> None:
    await dispatch_notification_outbox(application)


def build_expense_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("expense", begin_expense), CallbackQueryHandler(begin_expense, pattern=r"^main:expense$"), CommandHandler("myexpenses", my_expenses), CallbackQueryHandler(my_expenses, pattern=r"^main:myexpenses$")],
        states={
            CATEGORY: [CallbackQueryHandler(choose_category, pattern=r"^expcat:\d+$"), CallbackQueryHandler(choose_currency, pattern=r"^expcur:(KHR|USD)$"), CallbackQueryHandler(choose_source, pattern=r"^expsrc:(KHR_CASH|USD_CASH|ABA_KHQR)$"), CallbackQueryHandler(receipt_choice, pattern=r"^expreceipt:(add|skip)$"), CallbackQueryHandler(confirm_expense, pattern=r"^expconfirm:"), CallbackQueryHandler(cancel_expense, pattern=r"^expcancel$")],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason)],
            RECEIPT: [MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, receive_receipt)],
        },
        fallbacks=[CommandHandler("cancel", cancel_expense)],
        allow_reentry=True,
    )


def build_approval_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("approvals", pending_approvals), CallbackQueryHandler(pending_approvals, pattern=r"^main:approvals$"), CallbackQueryHandler(approval_action, pattern=r"^exp(approve|reject|question):\d+$")],
        states={DECISION_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, decision_reason)]},
        fallbacks=[CommandHandler("cancel", cancel_expense)],
        allow_reentry=True,
    )
