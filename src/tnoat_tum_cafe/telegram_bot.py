from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from .config import Settings
from .db import create_database_engine, session_factory
from .models import DiscountRule, PricingMode, Product, Sale, SaleStatus, User
from .services.auth import get_user_by_telegram_id, has_permission
from .services.business_days import active_business_day
from .services.catalog import active_categories, active_products, suggested_prices
from .services.money import format_money, parse_money
from .services.sales import CartItemInput, PaymentInput, post_sale, preview_sale, reverse_sale, staff_activity
from . import strings


SELECTING, MANUAL_NAME, PRICE_INPUT, QUANTITY_OTHER, SPLIT_CASH, CORRECTION_REASON, CUSTOM_DISCOUNT = range(7)
logger = logging.getLogger(__name__)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(strings.NEW_SALE, callback_data="main:new")],
        [InlineKeyboardButton(strings.NEW_EXPENSE, callback_data="main:expense")],
        [InlineKeyboardButton(strings.CASH, callback_data="main:cash")],
        [InlineKeyboardButton(strings.MY_ACCOUNT, callback_data="main:account")],
        [InlineKeyboardButton(strings.MY_EXPENSES, callback_data="main:myexpenses"), InlineKeyboardButton(strings.PENDING_APPROVALS, callback_data="main:approvals")],
        [InlineKeyboardButton(strings.CORRECT_LAST, callback_data="main:correct")],
    ])


def _cart(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("cart", {"items": [], "discount": 0})


def _to_inputs(cart: dict) -> list[CartItemInput]:
    return [CartItemInput(**item) for item in cart["items"]]


async def _actor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id if update.effective_user else 0
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        user = get_user_by_telegram_id(session, telegram_id)
        if user is None:
            if update.callback_query:
                await update.callback_query.answer(strings.UNAUTHORIZED, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(strings.UNAUTHORIZED)
            return None
        return user.id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _actor(update, context) is None:
        return ConversationHandler.END
    context.user_data.pop("cart", None)
    await update.effective_message.reply_text(f"{strings.WELCOME}\n\n{strings.MAIN_MENU}", reply_markup=_main_keyboard())
    return SELECTING


async def my_id(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id if update.effective_user else 0
    await update.effective_message.reply_text(f"Your numeric Telegram ID is: {telegram_id}")
    return ConversationHandler.END


async def main_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    actor_id = await _actor(update, context)
    if actor_id is None:
        return ConversationHandler.END
    action = query.data.split(":", 1)[1]
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = session.get(User, actor_id)
        if action == "account":
            sales = staff_activity(session, requester=actor, limit=10)
            lines = ["👤 MY ACCOUNT / គណនីខ្ញុំ", "Recent sales:"]
            if not sales:
                lines.append("No posted activity yet.")
            for sale in sales:
                lines.append(f"{sale.receipt_number} • {format_money(sale.total_minor, sale.currency)} • {sale.status}")
            await query.edit_message_text("\n".join(lines), reply_markup=_main_keyboard())
            return SELECTING
        if action == "correct":
            if not has_permission(session, actor, "sale.correct"):
                await query.edit_message_text(strings.UNAUTHORIZED, reply_markup=_main_keyboard())
                return SELECTING
            sale = session.scalar(select(Sale).where(Sale.staff_user_id == actor.id, Sale.status == SaleStatus.POSTED.value).order_by(Sale.posted_at.desc()).limit(1))
            if sale is None:
                await query.edit_message_text("No posted sale is available to correct.", reply_markup=_main_keyboard())
                return SELECTING
            context.user_data["correction_sale_id"] = sale.id
            await query.edit_message_text(f"↩️ Reverse {sale.receipt_number} ({format_money(sale.total_minor, sale.currency)})?\nSend the required correction reason, or /cancel.")
            return CORRECTION_REASON
        if not has_permission(session, actor, "sale.create"):
            await query.edit_message_text(strings.UNAUTHORIZED, reply_markup=_main_keyboard())
            return SELECTING
        if active_business_day(session) is None:
            await query.edit_message_text(strings.NO_BUSINESS_DAY, reply_markup=_main_keyboard())
            return SELECTING
        context.user_data["cart"] = {"items": [], "discount": 0}
        await _show_categories(query, session)
        return SELECTING


async def _show_categories(query, session) -> None:
    categories = active_categories(session)
    keyboard = [[InlineKeyboardButton(f"{category.icon or '📁'} {category.name}", callback_data=f"cat:{category.id}")] for category in categories]
    keyboard.append([InlineKeyboardButton(strings.MANUAL_ITEM, callback_data="manual")])
    keyboard.append([InlineKeyboardButton(strings.CART, callback_data="cart")])
    await query.edit_message_text("🧾 New Sale — choose a category:", reply_markup=InlineKeyboardMarkup(keyboard))


async def add_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        await _show_categories(query, session)
    return SELECTING


async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split(":")[1])
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        products = active_products(session, category_id)
    keyboard = [[InlineKeyboardButton(product.name, callback_data=f"prod:{product.id}")] for product in products]
    keyboard.extend([[InlineKeyboardButton(strings.MANUAL_ITEM, callback_data="manual")], [InlineKeyboardButton(strings.CART, callback_data="cart")]])
    await query.edit_message_text("Choose product / ជ្រើសរើសមុខទំនិញ៖", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING


async def select_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split(":")[1])
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        product = session.get(Product, product_id)
        if product is None or not product.is_active:
            await query.answer("Product unavailable", show_alert=True)
            return SELECTING
        context.user_data["pending_item"] = {"product_id": product.id}
        if product.pricing_mode == PricingMode.OPEN_PRICE.value:
            suggestions = suggested_prices(session, product.id)
            keyboard = [[InlineKeyboardButton(format_money(price.amount_minor, price.currency), callback_data=f"price:{price.currency}:{price.amount_minor}")] for price in suggestions]
            keyboard.extend([[InlineKeyboardButton("🇰🇭 Enter KHR price", callback_data="pricecur:KHR"), InlineKeyboardButton("🇺🇸 Enter USD price", callback_data="pricecur:USD")], [InlineKeyboardButton(strings.CANCEL, callback_data="cancel")]])
            await query.edit_message_text(f"{product.name}\nChoose or enter the actual price:", reply_markup=InlineKeyboardMarkup(keyboard))
            return SELECTING
    return await _show_quantity(query, context)


async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["pending_item"] = {"product_id": None}
    await query.edit_message_text("✍️ Enter the custom item name (maximum 160 characters), or /cancel:")
    return MANUAL_NAME


async def manual_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.effective_message.text.strip()
    if not name or len(name) > 160:
        await update.effective_message.reply_text("Name must contain 1–160 characters.")
        return MANUAL_NAME
    context.user_data["pending_item"]["manual_name"] = name
    keyboard = [[InlineKeyboardButton("🇰🇭 KHR", callback_data="pricecur:KHR"), InlineKeyboardButton("🇺🇸 USD", callback_data="pricecur:USD")]]
    await update.effective_message.reply_text("Choose item currency:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING


async def select_price_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["pending_item"]["manual_currency"] = query.data.split(":")[1]
    await query.edit_message_text(f"Enter price in {context.user_data['pending_item']['manual_currency']} (whole riel for KHR; up to 2 decimals for USD):")
    return PRICE_INPUT


async def select_suggested_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, currency, amount = query.data.split(":")
    context.user_data["pending_item"].update(manual_currency=currency, unit_price_minor=int(amount))
    return await _show_quantity(query, context)


async def price_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pending = context.user_data["pending_item"]
    try:
        pending["unit_price_minor"] = parse_money(update.effective_message.text, pending["manual_currency"])
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}. Try again or /cancel.")
        return PRICE_INPUT
    await update.effective_message.reply_text("Choose quantity:", reply_markup=_quantity_keyboard())
    return SELECTING


def _quantity_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(str(value), callback_data=f"qty:{value}") for value in range(1, 6)], [InlineKeyboardButton("Other", callback_data="qty:other"), InlineKeyboardButton(strings.CANCEL, callback_data="cancel")]])


async def _show_quantity(query, context) -> int:
    await query.edit_message_text("Choose quantity / ជ្រើសរើសចំនួន៖", reply_markup=_quantity_keyboard())
    return SELECTING


async def quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    raw = query.data.split(":")[1]
    if raw == "other":
        await query.edit_message_text("Enter quantity from 1 to 999:")
        return QUANTITY_OTHER
    return await _add_pending(query, context, int(raw))


async def quantity_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        value = int(update.effective_message.text.strip())
        if not 1 <= value <= 999:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Quantity must be a whole number from 1 to 999.")
        return QUANTITY_OTHER
    context.user_data["pending_item"]["quantity"] = value
    _cart(context)["items"].append(context.user_data.pop("pending_item"))
    await update.effective_message.reply_text("✅ Added to cart.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.ADD_MORE, callback_data="more"), InlineKeyboardButton(strings.CART, callback_data="cart")]]))
    return SELECTING


async def _add_pending(query, context, quantity_value: int) -> int:
    context.user_data["pending_item"]["quantity"] = quantity_value
    _cart(context)["items"].append(context.user_data.pop("pending_item"))
    await query.edit_message_text("✅ Added to cart.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.ADD_MORE, callback_data="more"), InlineKeyboardButton(strings.CART, callback_data="cart")]]))
    return SELECTING


async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cart = _cart(context)
    actor_id = await _actor(update, context)
    if actor_id is None:
        return ConversationHandler.END
    if not cart["items"]:
        await query.edit_message_text("🛒 Cart is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.ADD_MORE, callback_data="main:new")]]))
        return SELECTING
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        try:
            currency, subtotal, _, _ = preview_sale(session, items=_to_inputs(cart), discount_basis_points=0)
        except ValueError as exc:
            await query.edit_message_text(f"⚠️ {exc}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.CANCEL, callback_data="cancel")]]))
            return SELECTING
        rules = list(session.scalars(select(DiscountRule).where(DiscountRule.is_active.is_(True)).order_by(DiscountRule.basis_points)))
        actor = session.get(User, actor_id)
        custom_allowed = has_permission(session, actor, "sale.discount.custom")
    keyboard = [[InlineKeyboardButton(rule.name, callback_data=f"disc:{rule.basis_points}")] for rule in rules if not rule.requires_approval]
    if custom_allowed:
        keyboard.append([InlineKeyboardButton("🏷️ Custom Discount", callback_data="disc:custom")])
    keyboard.append([InlineKeyboardButton(strings.CANCEL, callback_data="cancel")])
    await query.edit_message_text(f"🛒 {len(cart['items'])} line item(s)\nSubtotal: {format_money(subtotal, currency)}\nChoose discount:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING


async def select_discount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cart = _cart(context)
    selected = query.data.split(":")[1]
    if selected == "custom":
        await query.edit_message_text("Enter custom discount percent from 0.01 through 99.99 (owner-authorized users only):")
        return CUSTOM_DISCOUNT
    cart["discount"] = int(selected)
    return await _show_payments(query, context)


async def custom_discount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        percent = Decimal(update.effective_message.text.strip())
        if not Decimal("0.01") <= percent <= Decimal("99.99") or percent.as_tuple().exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        await update.effective_message.reply_text("Enter a percent from 0.01 through 99.99 with at most two decimals.")
        return CUSTOM_DISCOUNT
    actor_id = await _actor(update, context)
    if actor_id is None:
        return ConversationHandler.END
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        actor = session.get(User, actor_id)
        if not has_permission(session, actor, "sale.discount.custom"):
            await update.effective_message.reply_text(strings.UNAUTHORIZED)
            return SELECTING
        cart = _cart(context)
        cart["discount"] = int(percent * 100)
        currency, subtotal, discount, total = preview_sale(session, items=_to_inputs(cart), discount_basis_points=cart["discount"])
        cart.update(currency=currency, subtotal=subtotal, discount_minor=discount, total=total)
    await update.effective_message.reply_text(f"Subtotal: {format_money(subtotal, currency)}\nDiscount: {format_money(discount, currency)}\nTotal: {format_money(total, currency)}\nChoose payment:", reply_markup=_payment_keyboard(context))
    return SELECTING


def _payment_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("💵 Cash", callback_data="pay:CASH"), InlineKeyboardButton("📱 ABA/KHQR", callback_data="pay:ABA_KHQR")]]
    if context.application.bot_data["settings"].enable_same_currency_split:
        keyboard.append([InlineKeyboardButton("➗ Cash + ABA Split", callback_data="pay:SPLIT")])
    return InlineKeyboardMarkup(keyboard)


async def _show_payments(query, context) -> int:
    cart = _cart(context)
    factory = context.application.bot_data["session_factory"]
    with factory() as session:
        currency, subtotal, discount, total = preview_sale(session, items=_to_inputs(cart), discount_basis_points=cart["discount"])
    cart.update(currency=currency, subtotal=subtotal, discount_minor=discount, total=total)
    await query.edit_message_text(f"Subtotal: {format_money(subtotal, currency)}\nDiscount: {format_money(discount, currency)}\nTotal: {format_money(total, currency)}\nChoose payment:", reply_markup=_payment_keyboard(context))
    return SELECTING


async def select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    method = query.data.split(":")[1]
    cart = _cart(context)
    if method == "SPLIT":
        await query.edit_message_text(f"Enter the CASH part in {cart['currency']}. ABA will receive the exact remainder:")
        return SPLIT_CASH
    cart["payments"] = [{"method": method, "currency": cart["currency"], "amount_minor": cart["total"]}]
    return await _review(query, context)


async def split_cash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cart = _cart(context)
    try:
        cash = parse_money(update.effective_message.text, cart["currency"])
        if cash >= cart["total"]:
            raise ValueError("Cash part must be less than the total")
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}. Try again or /cancel.")
        return SPLIT_CASH
    cart["payments"] = [{"method": "CASH", "currency": cart["currency"], "amount_minor": cash}, {"method": "ABA_KHQR", "currency": cart["currency"], "amount_minor": cart["total"] - cash}]
    token = uuid4().hex[:16]
    cart["confirm_token"] = token
    await update.effective_message.reply_text(_review_text(cart), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.CONFIRM, callback_data=f"confirm:{token}")], [InlineKeyboardButton(strings.CANCEL, callback_data="cancel")]]))
    return SELECTING


def _review_text(cart: dict) -> str:
    payment_text = " + ".join(f"{payment['method']} {format_money(payment['amount_minor'], payment['currency'])}" for payment in cart["payments"])
    return f"🧾 REVIEW BEFORE POSTING\nItems: {len(cart['items'])}\nSubtotal: {format_money(cart['subtotal'], cart['currency'])}\nDiscount: {format_money(cart['discount_minor'], cart['currency'])}\nTOTAL: {format_money(cart['total'], cart['currency'])}\nPayment: {payment_text}\n\nNothing is posted until Confirm."


async def _review(query, context) -> int:
    cart = _cart(context)
    token = uuid4().hex[:16]
    cart["confirm_token"] = token
    await query.edit_message_text(_review_text(cart), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(strings.CONFIRM, callback_data=f"confirm:{token}")], [InlineKeyboardButton(strings.CANCEL, callback_data="cancel")]]))
    return SELECTING


async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cart = _cart(context)
    token = query.data.split(":")[1]
    if token != cart.get("confirm_token"):
        await query.answer("Stale confirmation", show_alert=True)
        return SELECTING
    actor_id = await _actor(update, context)
    if actor_id is None:
        return ConversationHandler.END
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            sale, created = post_sale(session, actor=actor, items=_to_inputs(cart), discount_basis_points=cart["discount"], payments=[PaymentInput(**payment) for payment in cart["payments"]], idempotency_key=f"telegram-confirm:{token}")
            receipt, total, currency = sale.receipt_number, sale.total_minor, sale.currency
    except (ValueError, PermissionError) as exc:
        await query.edit_message_text(f"⚠️ Sale not posted: {exc}", reply_markup=_main_keyboard())
        return SELECTING
    context.user_data.pop("cart", None)
    await query.edit_message_text(f"✅ {'POSTED' if created else 'ALREADY POSTED'}\nReceipt: {receipt}\nTotal: {format_money(total, currency)}", reply_markup=_main_keyboard())
    return SELECTING


async def correction_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.effective_message.text.strip()
    actor_id = await _actor(update, context)
    if actor_id is None:
        return ConversationHandler.END
    token = uuid4().hex
    factory = context.application.bot_data["session_factory"]
    try:
        with factory() as session, session.begin():
            actor = session.get(User, actor_id)
            sale, _ = reverse_sale(session, actor=actor, sale_id=context.user_data["correction_sale_id"], reason=reason, idempotency_key=f"telegram-correction:{token}")
            receipt = sale.receipt_number
    except (ValueError, PermissionError) as exc:
        await update.effective_message.reply_text(f"⚠️ Correction not posted: {exc}", reply_markup=_main_keyboard())
        return SELECTING
    context.user_data.pop("correction_sale_id", None)
    await update.effective_message.reply_text(f"↩️ {receipt} reversed. Original history and payment reversal records were preserved.", reply_markup=_main_keyboard())
    return SELECTING


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("cart", None)
    context.user_data.pop("pending_item", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Cancelled safely. Nothing was posted.", reply_markup=_main_keyboard())
    else:
        await update.effective_message.reply_text("Cancelled safely. Nothing was posted.", reply_markup=_main_keyboard())
    return SELECTING


async def error_handler(_update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Telegram update failed: %s", type(context.error).__name__)


def build_application(settings: Settings) -> Application:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to build the live Telegram application")
    engine = create_database_engine(settings.database_url)
    from .telegram_expenses import build_approval_handler, build_expense_handler, expense_reply_command, startup_notification_dispatch
    from .telegram_cash import build_cash_handler
    from .telegram_closing import closing_handlers
    from .telegram_insights import insight_handlers
    application = ApplicationBuilder().token(settings.telegram_bot_token).post_init(startup_notification_dispatch).build()
    application.bot_data.update(settings=settings, session_factory=session_factory(engine))
    application.add_handler(build_expense_handler(), group=0)
    application.add_handler(build_cash_handler(), group=0)
    for handler in closing_handlers(): application.add_handler(handler, group=1)
    for handler in insight_handlers(): application.add_handler(handler, group=1)
    application.add_handler(build_approval_handler(), group=1)
    application.add_handler(CommandHandler("expense_reply", expense_reply_command), group=1)
    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING: [CallbackQueryHandler(main_action, pattern=r"^main:(new|account|correct)$"), CallbackQueryHandler(add_more, pattern=r"^more$"), CallbackQueryHandler(select_category, pattern=r"^cat:\d+$"), CallbackQueryHandler(select_product, pattern=r"^prod:\d+$"), CallbackQueryHandler(manual_start, pattern=r"^manual$"), CallbackQueryHandler(select_price_currency, pattern=r"^pricecur:(KHR|USD)$"), CallbackQueryHandler(select_suggested_price, pattern=r"^price:(KHR|USD):\d+$"), CallbackQueryHandler(quantity, pattern=r"^qty:"), CallbackQueryHandler(show_cart, pattern=r"^cart$"), CallbackQueryHandler(select_discount, pattern=r"^disc:(\d+|custom)$"), CallbackQueryHandler(select_payment, pattern=r"^pay:"), CallbackQueryHandler(confirm_sale, pattern=r"^confirm:"), CallbackQueryHandler(cancel, pattern=r"^cancel$")],
            MANUAL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_name)],
            PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_input)],
            QUANTITY_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_other)],
            SPLIT_CASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, split_cash)],
            CORRECTION_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_reason)],
            CUSTOM_DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_discount)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start), CommandHandler("myid", my_id)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("myid", my_id), group=0)
    application.add_handler(conversation, group=2)
    application.add_error_handler(error_handler)
    return application


def run_bot(settings: Settings) -> None:
    build_application(settings).run_polling(drop_pending_updates=False)
