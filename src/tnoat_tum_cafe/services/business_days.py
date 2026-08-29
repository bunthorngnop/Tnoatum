from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BusinessDay, BusinessDayStatus, User
from .audit import append_audit


def active_business_day(session: Session) -> BusinessDay | None:
    return session.scalar(select(BusinessDay).where(BusinessDay.status != BusinessDayStatus.CLOSED.value))


def business_day_for_transaction(session: Session) -> BusinessDay:
    day = active_business_day(session)
    if day is None:
        raise ValueError("No open business day; an authorized user must open one")
    return day


def open_business_day(session: Session, *, business_date: date, actor: User, opened_at: datetime) -> BusinessDay:
    if active_business_day(session) is not None:
        raise ValueError("A business day is already active")
    day = BusinessDay(business_date=business_date, opened_by_user_id=actor.id, opened_at=opened_at)
    session.add(day)
    session.flush()
    append_audit(session, action="BUSINESS_DAY_OPENED", entity_type="business_day", entity_id=str(day.id), actor=actor, new_values={"business_date": business_date.isoformat(), "status": day.status})
    return day


def start_closing(session: Session, *, day: BusinessDay, actor: User, occurred_at: datetime) -> None:
    if day.status != BusinessDayStatus.OPEN.value:
        raise ValueError("Only an open business day can start closing")
    day.status = BusinessDayStatus.CLOSING_PENDING.value
    day.closing_started_at = occurred_at
    day.closing_started_by_user_id = actor.id
    append_audit(session, action="BUSINESS_DAY_CLOSING_STARTED", entity_type="business_day", entity_id=str(day.id), actor=actor, old_values={"status": "OPEN"}, new_values={"status": "CLOSING_PENDING"})


def cancel_closing(session: Session, *, day: BusinessDay, actor: User, reason: str) -> None:
    if day.status != BusinessDayStatus.CLOSING_PENDING.value:
        raise ValueError("Closing is not pending")
    if not reason.strip():
        raise ValueError("A reason is required to cancel closing")
    day.status = BusinessDayStatus.OPEN.value
    day.closing_started_at = None
    day.closing_started_by_user_id = None
    append_audit(session, action="BUSINESS_DAY_CLOSING_CANCELLED", entity_type="business_day", entity_id=str(day.id), actor=actor, old_values={"status": "CLOSING_PENDING"}, new_values={"status": "OPEN"}, reason=reason)

