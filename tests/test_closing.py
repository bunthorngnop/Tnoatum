from datetime import date, datetime, time, timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import BusinessDayStatus, ClosingRecord, NotificationOutbox, User
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.cash import record_cash_count, record_cash_movement
from tnoat_tum_cafe.services.closing import begin_closing, finalize_closing, reopen_business_day

@pytest.fixture
def closing_setup(session:Session,owner:User):
    seed_foundation(session,Settings("Tnoat Tum Cafe","Asia/Phnom_Penh",time(8),time(17),time(18),"sqlite:///:memory:",(owner.telegram_user_id,),("KHR","USD"),Path("backups"),30))
    day=open_business_day(session,business_date=date(2026,8,29),actor=owner,opened_at=datetime(2026,8,29,1,tzinfo=timezone.utc))
    record_cash_movement(session,actor=owner,movement_type="OPENING_FLOAT",direction="INFLOW",amount_minor=10000,currency="KHR",reason="Open",idempotency_key="open")
    count,_=record_cash_count(session,actor=owner,actual_khr_minor=9500,actual_usd_minor=0,idempotency_key="count")
    session.commit(); return owner,day,count

def test_closing_requires_pending_and_explanation(session,closing_setup):
    owner,day,count=closing_setup
    with pytest.raises(ValueError,match="started"): finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr="short",explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="early")
    begin_closing(session,actor=owner,idempotency_key="begin")
    with pytest.raises(ValueError,match="KHR discrepancy"): finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr=None,explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="missing")

def test_close_is_immutable_idempotent_and_notifies_owner(session,closing_setup):
    owner,day,count=closing_setup; begin_closing(session,actor=owner,idempotency_key="begin")
    closing,created=finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr="Counted short",explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="finish",closed_at=datetime(2026,8,30,18,tzinfo=timezone.utc)); session.commit()
    duplicate,again=finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr="Counted short",explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="finish")
    assert created and not again and duplicate.id==closing.id and day.status==BusinessDayStatus.CLOSED.value and closing.closed_at.date()==date(2026,8,30)
    assert session.scalar(select(NotificationOutbox).where(NotificationOutbox.notification_type=="BUSINESS_DAY_CLOSED"))
    session.delete(closing)
    with pytest.raises(ValueError): session.flush()
    session.rollback()

def test_aba_confirmation_and_tolerance(session,closing_setup):
    owner,day,count=closing_setup; begin_closing(session,actor=owner,idempotency_key="begin")
    with pytest.raises(ValueError,match="ABA"): finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=False,explanation_khr=None,explanation_usd=None,tolerance_khr_minor=1000,tolerance_usd_minor=0,idempotency_key="noaba")
    closing,_=finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr=None,explanation_usd=None,tolerance_khr_minor=1000,tolerance_usd_minor=0,idempotency_key="within")
    assert closing.difference_khr_minor==-500

def test_reopen_requires_reason_and_preserves_closing(session,closing_setup):
    owner,day,count=closing_setup; begin_closing(session,actor=owner,idempotency_key="begin"); closing,_=finalize_closing(session,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr="short",explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="finish"); session.commit()
    with pytest.raises(ValueError,match="reason"): reopen_business_day(session,actor=owner,business_day_id=day.id,reason="",idempotency_key="bad")
    row,created=reopen_business_day(session,actor=owner,business_day_id=day.id,reason="Continue late service",idempotency_key="reopen"); session.commit()
    assert created and day.status==BusinessDayStatus.OPEN.value and session.get(ClosingRecord,closing.id)

def test_no_automatic_time_or_midnight_close(session,closing_setup):
    _,day,_=closing_setup
    assert day.status==BusinessDayStatus.OPEN.value and day.business_date==date(2026,8,29)
