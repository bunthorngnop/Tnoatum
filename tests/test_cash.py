from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import AuditLog, CashCount, CashMovement, LedgerEntry, RetainedFloat, Role, User, UserRole
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.cash import cash_history, cash_status, record_cash_count, record_cash_movement, record_retained_float, reverse_cash_movement, suggested_retained_float


@pytest.fixture
def cash_setup(session: Session, owner: User) -> dict:
    settings = Settings("Tnoat Tum Cafe", "Asia/Phnom_Penh", time(8), time(17), time(18), "sqlite:///:memory:", (owner.telegram_user_id,), ("KHR", "USD"), Path("backups"), 30)
    seed_foundation(session, settings)
    staff_role = session.scalar(select(Role).where(Role.code == "STAFF"))
    staff = User(telegram_user_id=880001, display_name="No Cash Permission")
    session.add(staff); session.flush(); session.add(UserRole(user_id=staff.id, role_id=staff_role.id))
    day = open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=datetime(2026, 8, 29, 1, tzinfo=timezone.utc))
    session.commit()
    return {"owner": owner, "staff": staff, "day": day}


def _move(session, setup, kind, amount, currency="KHR", direction=None, key=None, reason="Authorized test movement"):
    direction = direction or ("INFLOW" if kind in {"OPENING_FLOAT", "DEPOSIT"} else "OUTFLOW")
    movement, created = record_cash_movement(session, actor=setup["owner"], movement_type=kind, direction=direction, amount_minor=amount, currency=currency, reason=reason, idempotency_key=key or f"{kind}-{currency}-{amount}")
    session.commit()
    return movement, created


def _ledger(session, setup, *, direction, amount, currency, method, entry_type):
    session.add(LedgerEntry(business_day_id=setup["day"].id, entry_type=entry_type, direction=direction, amount_minor=amount, currency=currency, payment_method=method, source_entity_type="test", source_entity_id=f"{entry_type}-{currency}-{amount}-{method}", actor_user_id=setup["owner"].id))
    session.commit()


def test_khr_opening_cash(cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", 300_000)
    assert cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 300_000


def test_usd_opening_cash(cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", 4250, "USD")
    assert cash_status(session, actor=cash_setup["owner"]).expected_usd_minor == 4250


def test_duplicate_opening_prevented(cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", 10_000)
    with pytest.raises(ValueError, match="already exists"):
        record_cash_movement(session, actor=cash_setup["owner"], movement_type="OPENING_FLOAT", direction="INFLOW", amount_minor=20_000, currency="KHR", reason="Wrong duplicate", idempotency_key="different-opening")


def test_opening_cash_is_not_revenue(cash_setup, session):
    movement, _ = _move(session, cash_setup, "OPENING_FLOAT", 10_000)
    entry = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_id == str(movement.id)))
    assert entry.entry_type == "CASH_OPENING_FLOAT" and "SALE" not in entry.entry_type


@pytest.mark.parametrize("currency,amount", [("KHR", 4000), ("USD", 250)])
def test_cash_sale_increases_expected(currency, amount, cash_setup, session):
    _ledger(session, cash_setup, direction="INFLOW", amount=amount, currency=currency, method="CASH", entry_type="SALE")
    status = cash_status(session, actor=cash_setup["owner"])
    assert (status.expected_khr_minor if currency == "KHR" else status.expected_usd_minor) == amount


def test_aba_sale_excluded_from_cash(cash_setup, session):
    _ledger(session, cash_setup, direction="INFLOW", amount=9000, currency="KHR", method="ABA_KHQR", entry_type="SALE")
    status = cash_status(session, actor=cash_setup["owner"])
    assert status.expected_khr_minor == 0 and status.aba_khr_minor == 9000


@pytest.mark.parametrize("currency,amount", [("KHR", 4000), ("USD", 250)])
def test_cash_expense_reduces_expected(currency, amount, cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", amount * 2, currency)
    _ledger(session, cash_setup, direction="OUTFLOW", amount=amount, currency=currency, method="CASH", entry_type="EXPENSE")
    status = cash_status(session, actor=cash_setup["owner"])
    assert (status.expected_khr_minor if currency == "KHR" else status.expected_usd_minor) == amount


def test_aba_expense_excluded_from_cash(cash_setup, session):
    _ledger(session, cash_setup, direction="OUTFLOW", amount=4000, currency="KHR", method="ABA_KHQR", entry_type="EXPENSE")
    assert cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 0


def test_deposit_increases_expected(cash_setup, session):
    _move(session, cash_setup, "DEPOSIT", 5000)
    assert cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 5000


@pytest.mark.parametrize("kind", ["WITHDRAWAL", "OWNER_WITHDRAWAL"])
def test_withdrawals_reduce_expected(kind, cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", 10_000)
    _move(session, cash_setup, kind, 3000, key=kind)
    assert cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 7000


def test_currencies_remain_separate(cash_setup, session):
    _move(session, cash_setup, "DEPOSIT", 10_000, "KHR"); _move(session, cash_setup, "DEPOSIT", 250, "USD")
    status = cash_status(session, actor=cash_setup["owner"])
    assert (status.expected_khr_minor, status.expected_usd_minor) == (10_000, 250)


def test_retained_float_is_evidence_not_automatic_cash(cash_setup, session):
    retained, _ = record_retained_float(session, actor=cash_setup["owner"], currency="KHR", amount_minor=300_000, reason="Tomorrow float", idempotency_key="retain-1")
    session.commit()
    assert retained.amount_minor == 300_000 and cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 0


def test_retained_float_can_be_suggested_not_applied(cash_setup, session):
    retained, _ = record_retained_float(session, actor=cash_setup["owner"], currency="USD", amount_minor=1000, reason="Suggestion", idempotency_key="retain-usd")
    session.commit()
    assert suggested_retained_float(session, currency="USD", current_business_day_id=999).id == retained.id


def test_cash_count_stores_actual_and_discrepancy(cash_setup, session):
    _move(session, cash_setup, "OPENING_FLOAT", 10_000)
    count, _ = record_cash_count(session, actor=cash_setup["owner"], actual_khr_minor=9500, actual_usd_minor=200, idempotency_key="count-1")
    session.commit()
    assert (count.actual_khr_minor, count.actual_usd_minor, count.difference_khr_minor, count.difference_usd_minor) == (9500, 200, -500, 200)


def test_previous_cash_counts_preserved(cash_setup, session):
    first, _ = record_cash_count(session, actor=cash_setup["owner"], actual_khr_minor=1, actual_usd_minor=2, idempotency_key="count-a")
    second, _ = record_cash_count(session, actor=cash_setup["owner"], actual_khr_minor=3, actual_usd_minor=4, idempotency_key="count-b")
    session.commit()
    assert first.id != second.id and session.query(CashCount).count() == 2


def test_adjustment_requires_reason(cash_setup, session):
    with pytest.raises(ValueError, match="reason"):
        record_cash_movement(session, actor=cash_setup["owner"], movement_type="ADJUSTMENT", direction="INFLOW", amount_minor=1, currency="KHR", reason="", idempotency_key="adjust")


def test_unauthorized_cash_action_blocked(cash_setup, session):
    with pytest.raises(PermissionError):
        record_cash_movement(session, actor=cash_setup["staff"], movement_type="DEPOSIT", direction="INFLOW", amount_minor=1, currency="KHR", reason="No authority", idempotency_key="blocked")


def test_duplicate_callback_is_idempotent(cash_setup, session):
    first, created = _move(session, cash_setup, "DEPOSIT", 100, key="callback-77")
    second, duplicate = record_cash_movement(session, actor=cash_setup["owner"], movement_type="DEPOSIT", direction="INFLOW", amount_minor=100, currency="KHR", reason="Authorized test movement", idempotency_key="callback-77")
    assert created is True and duplicate is False and first.id == second.id and session.query(CashMovement).count() == 1


def test_cash_movement_cannot_be_deleted(cash_setup, session):
    movement, _ = _move(session, cash_setup, "DEPOSIT", 100)
    session.delete(movement)
    with pytest.raises(ValueError, match="cannot be deleted"):
        session.flush()
    session.rollback()


def test_reversal_preserves_original(cash_setup, session):
    movement, _ = _move(session, cash_setup, "DEPOSIT", 100)
    reversal, created = reverse_cash_movement(session, actor=cash_setup["owner"], movement_id=movement.id, reason="Entry was duplicated", idempotency_key="reverse-1")
    session.commit()
    assert created and reversal.reversed_movement_id == movement.id and session.get(CashMovement, movement.id) is not None
    assert cash_status(session, actor=cash_setup["owner"]).expected_khr_minor == 0


def test_cross_midnight_uses_originating_business_day(cash_setup, session):
    movement, _ = record_cash_movement(session, actor=cash_setup["owner"], movement_type="DEPOSIT", direction="INFLOW", amount_minor=100, currency="KHR", reason="After midnight", idempotency_key="late", occurred_at=datetime(2026, 8, 30, 18, tzinfo=timezone.utc))
    assert movement.business_day_id == cash_setup["day"].id


def test_cash_audit_and_history(cash_setup, session):
    movement, _ = _move(session, cash_setup, "OWNER_WITHDRAWAL", 100)
    assert session.scalar(select(AuditLog).where(AuditLog.entity_type == "cash_movement", AuditLog.entity_id == str(movement.id)))
    assert cash_history(session, actor=cash_setup["owner"])[0].id == movement.id


def test_count_duplicate_callback_does_not_duplicate(cash_setup, session):
    first, created = record_cash_count(session, actor=cash_setup["owner"], actual_khr_minor=0, actual_usd_minor=0, idempotency_key="same-count")
    session.commit()
    second, duplicate = record_cash_count(session, actor=cash_setup["owner"], actual_khr_minor=99, actual_usd_minor=99, idempotency_key="same-count")
    assert created and not duplicate and first.id == second.id and session.query(CashCount).count() == 1
