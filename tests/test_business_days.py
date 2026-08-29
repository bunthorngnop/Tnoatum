from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tnoat_tum_cafe.models import AuditLog, BusinessDayStatus, User
from tnoat_tum_cafe.services.business_days import business_day_for_transaction, cancel_closing, open_business_day, start_closing


def test_cross_midnight_keeps_originating_business_day(session: Session, owner: User) -> None:
    opened = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    day = open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=opened)
    session.commit()
    after_midnight = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    assert after_midnight.date() != day.business_date
    assert business_day_for_transaction(session).id == day.id


def test_only_one_active_business_day(session: Session, owner: User) -> None:
    open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="already active"):
        open_business_day(session, business_date=date(2026, 8, 30), actor=owner, opened_at=datetime.now(timezone.utc))


def test_closing_state_change_and_cancel_are_audited(session: Session, owner: User) -> None:
    day = open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=datetime.now(timezone.utc))
    start_closing(session, day=day, actor=owner, occurred_at=datetime.now(timezone.utc))
    assert day.status == BusinessDayStatus.CLOSING_PENDING.value
    cancel_closing(session, day=day, actor=owner, reason="Continue serving customer")
    session.commit()
    assert day.status == BusinessDayStatus.OPEN.value
    assert session.query(AuditLog).count() == 3

