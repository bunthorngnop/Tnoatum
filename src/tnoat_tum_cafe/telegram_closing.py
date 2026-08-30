from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from sqlalchemy import select
from .models import CashCount, User
from .services.auth import get_user_by_telegram_id
from .services.closing import begin_closing, finalize_closing
from .services.money import format_money

async def close_day(update:Update,context:ContextTypes.DEFAULT_TYPE):
    with context.application.bot_data["session_factory"]() as session,session.begin():
        actor=get_user_by_telegram_id(session,update.effective_user.id)
        if not actor: await update.effective_message.reply_text("🔒 Unauthorized"); return
        try:
            day,_=begin_closing(session,actor=actor,idempotency_key=f"telegram-close-start:{update.update_id}")
            count=session.scalar(select(CashCount).where(CashCount.business_day_id==day.id).order_by(CashCount.id.desc()).limit(1))
            if not count: raise ValueError("Record a Cash Count before closing")
            await update.effective_message.reply_text(f"🌙 CLOSING REVIEW\nBusiness date: {day.business_date}\nKHR expected/actual/difference: {format_money(count.expected_khr_minor,'KHR')} / {format_money(count.actual_khr_minor,'KHR')} / {format_money(count.difference_khr_minor,'KHR')}\nUSD expected/actual/difference: {format_money(count.expected_usd_minor,'USD')} / {format_money(count.actual_usd_minor,'USD')} / {format_money(count.difference_usd_minor,'USD')}\nConfirm ABA and close with:\n/confirm_close {count.id} KHR_EXPLANATION | USD_EXPLANATION")
        except (ValueError,PermissionError) as exc: await update.effective_message.reply_text(f"⚠️ {exc}")

async def confirm_close(update:Update,context:ContextTypes.DEFAULT_TYPE):
    raw=" ".join(context.args)
    try:
        count_text,explanations=raw.split(" ",1); parts=explanations.split("|",1); khr=parts[0].strip() or None; usd=parts[1].strip() if len(parts)>1 else None
        with context.application.bot_data["session_factory"]() as session,session.begin():
            actor=get_user_by_telegram_id(session,update.effective_user.id); settings=context.application.bot_data["settings"]
            closing,created=finalize_closing(session,actor=actor,cash_count_id=int(count_text),aba_confirmed=True,explanation_khr=khr,explanation_usd=usd,tolerance_khr_minor=settings.closing_tolerance_khr_minor,tolerance_usd_minor=settings.closing_tolerance_usd_minor,idempotency_key=f"telegram-close-final:{update.update_id}")
        await update.effective_message.reply_text(f"🔒 Business day {'closed' if created else 'already closed'}. Closing #{closing.id}. Owner notification queued.")
    except (ValueError,PermissionError) as exc: await update.effective_message.reply_text(f"⚠️ Not closed: {exc}")

def closing_handlers(): return [CommandHandler("close_day",close_day),CommandHandler("confirm_close",confirm_close)]
