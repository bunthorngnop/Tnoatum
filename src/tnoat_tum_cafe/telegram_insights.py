from telegram import Update
from telegram.ext import CommandHandler,ContextTypes
from .services.auth import get_user_by_telegram_id
from .services.insights import owner_insights,toggle_favorite
async def favorite(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        product_id=int(context.args[0])
        with context.application.bot_data["session_factory"]() as session,session.begin():
            user=get_user_by_telegram_id(session,update.effective_user.id)
            if not user: raise PermissionError("Unauthorized")
            active=toggle_favorite(session,user=user,product_id=product_id)
        await update.effective_message.reply_text("⭐ Favorite saved" if active else "Favorite removed")
    except (ValueError,IndexError,PermissionError) as exc: await update.effective_message.reply_text(f"⚠️ {exc}. Usage: /favorite PRODUCT_ID")
async def insights(update:Update,context:ContextTypes.DEFAULT_TYPE):
    try:
        with context.application.bot_data["session_factory"]() as session:
            user=get_user_by_telegram_id(session,update.effective_user.id)
            if not user: raise PermissionError("Unauthorized")
            data=owner_insights(session,actor=user)
        await update.effective_message.reply_text(f"📊 LOCAL INSIGHTS\nBusiest: {data['busiest_hours']}\nCorrections: {data['correction_count']}\nUnusual discounts: {len(data['unusual_discounts'])}\nUnusual expenses: {len(data['unusual_expenses'])}\nSuggestions: {len(data['pending_suggestions'])}")
    except PermissionError as exc: await update.effective_message.reply_text(f"🔒 {exc}")
def insight_handlers(): return [CommandHandler("favorite",favorite),CommandHandler("insights",insights)]
