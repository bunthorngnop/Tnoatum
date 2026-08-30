from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..models import BusinessDay, BusinessDayReopening, BusinessDayStatus, CashCount, CashMovement, ClosingRecord, Expense, NotificationOutbox, Role, User, UserRole, utc_now
from .audit import append_audit
from .auth import has_permission
from .business_days import active_business_day, start_closing
from .cash import cash_status
from .money import format_money

def begin_closing(session: Session, *, actor: User, idempotency_key: str, occurred_at: datetime | None = None) -> tuple[BusinessDay, bool]:
    if not has_permission(session, actor, "business_day.close"):
        raise PermissionError("User lacks business_day.close permission")
    day = active_business_day(session)
    if day is None:
        raise ValueError("No active business day")
    if day.status == BusinessDayStatus.CLOSING_PENDING.value:
        return day, False
    start_closing(session, day=day, actor=actor, occurred_at=occurred_at or utc_now())
    append_audit(session, action="CLOSING_WORKFLOW_STARTED", entity_type="business_day", entity_id=str(day.id), actor=actor, correlation_id=idempotency_key)
    return day, True

def closing_review(session: Session, *, actor: User, cash_count_id: int) -> dict:
    if not has_permission(session, actor, "business_day.close"):
        raise PermissionError("User lacks business_day.close permission")
    day = active_business_day(session)
    count = session.get(CashCount, cash_count_id)
    if day is None or count is None or count.business_day_id != day.id:
        raise ValueError("Cash count does not belong to the active business day")
    status = cash_status(session, actor=actor, business_day_id=day.id)
    return {"day": day, "count": count, "aba_khr_minor": status.aba_khr_minor, "aba_usd_minor": status.aba_usd_minor, "expense_count": session.scalar(select(func.count(Expense.id)).where(Expense.business_day_id == day.id)) or 0, "cash_movement_count": session.scalar(select(func.count(CashMovement.id)).where(CashMovement.business_day_id == day.id)) or 0}

def finalize_closing(session: Session, *, actor: User, cash_count_id: int, aba_confirmed: bool, explanation_khr: str | None, explanation_usd: str | None, tolerance_khr_minor: int, tolerance_usd_minor: int, idempotency_key: str, closed_at: datetime | None = None) -> tuple[ClosingRecord, bool]:
    existing = session.scalar(select(ClosingRecord).where(ClosingRecord.idempotency_key == idempotency_key))
    if existing: return existing, False
    review = closing_review(session, actor=actor, cash_count_id=cash_count_id)
    day, count = review["day"], review["count"]
    if day.status != BusinessDayStatus.CLOSING_PENDING.value: raise ValueError("Closing has not been started")
    if not aba_confirmed: raise ValueError("ABA/KHQR review must be confirmed")
    if abs(count.difference_khr_minor) > tolerance_khr_minor and not (explanation_khr or "").strip(): raise ValueError("KHR discrepancy explanation is required")
    if abs(count.difference_usd_minor) > tolerance_usd_minor and not (explanation_usd or "").strip(): raise ValueError("USD discrepancy explanation is required")
    timestamp = closed_at or utc_now()
    record = ClosingRecord(business_day_id=day.id, cash_count_id=count.id, expected_khr_minor=count.expected_khr_minor, actual_khr_minor=count.actual_khr_minor, difference_khr_minor=count.difference_khr_minor, expected_usd_minor=count.expected_usd_minor, actual_usd_minor=count.actual_usd_minor, difference_usd_minor=count.difference_usd_minor, aba_khr_minor=review["aba_khr_minor"], aba_usd_minor=review["aba_usd_minor"], expense_count=review["expense_count"], cash_movement_count=review["cash_movement_count"], explanation_khr=(explanation_khr or "").strip() or None, explanation_usd=(explanation_usd or "").strip() or None, aba_confirmed=True, closed_by_user_id=actor.id, closed_at=timestamp, idempotency_key=idempotency_key)
    session.add(record); session.flush()
    day.status=BusinessDayStatus.CLOSED.value; day.closed_at=timestamp; day.closed_by_user_id=actor.id
    message=f"🌙 Tnoat Tum Cafe Closing\nBusiness date: {day.business_date}\nCloser: {actor.display_name}\nKHR expected/actual/difference: {format_money(count.expected_khr_minor,'KHR')} / {format_money(count.actual_khr_minor,'KHR')} / {format_money(count.difference_khr_minor,'KHR')}\nUSD expected/actual/difference: {format_money(count.expected_usd_minor,'USD')} / {format_money(count.actual_usd_minor,'USD')} / {format_money(count.difference_usd_minor,'USD')}\nABA/KHQR: {format_money(review['aba_khr_minor'],'KHR')} | {format_money(review['aba_usd_minor'],'USD')}\nExpenses: {review['expense_count']} | Cash movements: {review['cash_movement_count']}"
    owner_role=session.scalar(select(Role).where(Role.code=="OWNER"))
    if owner_role:
        owners=session.scalars(select(User).join(UserRole,UserRole.user_id==User.id).where(UserRole.role_id==owner_role.id,User.is_active.is_(True))).all()
        for owner in owners: session.add(NotificationOutbox(recipient_user_id=owner.id,notification_type="BUSINESS_DAY_CLOSED",entity_type="closing_record",entity_id=str(record.id),message=message))
    append_audit(session,action="BUSINESS_DAY_CLOSED",entity_type="closing_record",entity_id=str(record.id),actor=actor,new_values={"business_day_id":day.id,"difference_khr_minor":count.difference_khr_minor,"difference_usd_minor":count.difference_usd_minor},correlation_id=idempotency_key)
    return record, True

def reopen_business_day(session: Session, *, actor: User, business_day_id: int, reason: str, idempotency_key: str) -> tuple[BusinessDayReopening,bool]:
    if not has_permission(session, actor, "business_day.reopen"): raise PermissionError("User lacks business_day.reopen permission")
    existing=session.scalar(select(BusinessDayReopening).where(BusinessDayReopening.idempotency_key==idempotency_key))
    if existing:return existing,False
    day=session.get(BusinessDay,business_day_id)
    if not day or day.status!=BusinessDayStatus.CLOSED.value: raise ValueError("Business day is not closed")
    if active_business_day(session) is not None: raise ValueError("Another business day is active")
    clean=reason.strip()
    if not clean: raise ValueError("Reopening reason is required")
    row=BusinessDayReopening(business_day_id=day.id,reason=clean,reopened_by_user_id=actor.id,idempotency_key=idempotency_key)
    session.add(row); day.status=BusinessDayStatus.OPEN.value; day.closed_at=None; day.closed_by_user_id=None
    append_audit(session,action="BUSINESS_DAY_REOPENED",entity_type="business_day",entity_id=str(day.id),actor=actor,reason=clean,correlation_id=idempotency_key)
    return row,True
