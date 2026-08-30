from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import CashCount, CashMovement, CashMovementType, Currency, IdempotencyRecord, LedgerEntry, PaymentMethod, RetainedFloat, User, utc_now
from .audit import append_audit
from .auth import has_permission
from .business_days import business_day_for_transaction


@dataclass(frozen=True)
class CashStatus:
    business_day_id: int
    expected_khr_minor: int
    expected_usd_minor: int
    aba_khr_minor: int
    aba_usd_minor: int
    last_count: CashCount | None


_PERMISSION = {
    CashMovementType.OPENING_FLOAT.value: "cash.open",
    CashMovementType.DEPOSIT.value: "cash.deposit",
    CashMovementType.WITHDRAWAL.value: "cash.withdraw",
    CashMovementType.OWNER_WITHDRAWAL.value: "cash.owner_withdraw",
    CashMovementType.ADJUSTMENT.value: "cash.adjust",
}


def _validate_key(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 160:
        raise ValueError("A valid idempotency key is required")
    return value


def _require(session: Session, actor: User, permission: str) -> None:
    if not actor.is_active or not has_permission(session, actor, permission):
        append_audit(session, action="CASH_PERMISSION_DENIED", entity_type="permission", entity_id=permission, actor=actor, new_values={"permission": permission})
        raise PermissionError(f"User lacks {permission} permission")


def _expected_for(session: Session, business_day_id: int, currency: str, payment_method: str) -> int:
    value = session.scalar(select(func.coalesce(func.sum(case((LedgerEntry.direction == "INFLOW", LedgerEntry.amount_minor), else_=-LedgerEntry.amount_minor)), 0)).where(LedgerEntry.business_day_id == business_day_id, LedgerEntry.currency == currency, LedgerEntry.payment_method == payment_method))
    return int(value or 0)


def cash_status(session: Session, *, actor: User, business_day_id: int | None = None) -> CashStatus:
    _require(session, actor, "cash.view")
    day = business_day_for_transaction(session) if business_day_id is None else None
    day_id = day.id if day else business_day_id
    last_count = session.scalar(select(CashCount).where(CashCount.business_day_id == day_id).order_by(CashCount.counted_at.desc(), CashCount.id.desc()).limit(1))
    return CashStatus(day_id, _expected_for(session, day_id, "KHR", "CASH"), _expected_for(session, day_id, "USD", "CASH"), _expected_for(session, day_id, "KHR", "ABA_KHQR"), _expected_for(session, day_id, "USD", "ABA_KHQR"), last_count)


def record_cash_movement(session: Session, *, actor: User, movement_type: str, direction: str, amount_minor: int, currency: str, reason: str, idempotency_key: str, related_entity_type: str | None = None, related_entity_id: str | None = None, occurred_at: datetime | None = None) -> tuple[CashMovement, bool]:
    key = _validate_key(idempotency_key)
    kind = CashMovementType(movement_type).value
    if kind == CashMovementType.REVERSAL.value:
        raise ValueError("Use reverse_cash_movement for reversals")
    _require(session, actor, _PERMISSION[kind])
    existing = session.scalar(select(CashMovement).where(CashMovement.idempotency_key == key))
    if existing:
        return existing, False
    if currency not in {Currency.KHR.value, Currency.USD.value} or direction not in {"INFLOW", "OUTFLOW"} or amount_minor <= 0:
        raise ValueError("Movement currency, direction, and amount are invalid")
    required_direction = {"OPENING_FLOAT": "INFLOW", "DEPOSIT": "INFLOW", "WITHDRAWAL": "OUTFLOW", "OWNER_WITHDRAWAL": "OUTFLOW"}.get(kind)
    if required_direction and direction != required_direction:
        raise ValueError(f"{kind} must use {required_direction}")
    clean_reason = reason.strip()
    if not clean_reason or len(clean_reason) > 1000:
        raise ValueError("A movement reason is required")
    day = business_day_for_transaction(session)
    if kind == "OPENING_FLOAT" and session.scalar(select(CashMovement).where(CashMovement.business_day_id == day.id, CashMovement.movement_type == kind, CashMovement.currency == currency)):
        raise ValueError(f"Opening {currency} cash already exists; use an adjustment or reversal")
    timestamp = occurred_at or utc_now()
    movement = CashMovement(business_day_id=day.id, movement_type=kind, direction=direction, amount_minor=amount_minor, currency=currency, reason=clean_reason, actor_user_id=actor.id, related_entity_type=related_entity_type, related_entity_id=related_entity_id, approved_by_user_id=actor.id if kind == "ADJUSTMENT" else None, idempotency_key=key, occurred_at=timestamp)
    session.add(movement)
    session.flush()
    session.add(LedgerEntry(business_day_id=day.id, entry_type=f"CASH_{kind}", direction=direction, amount_minor=amount_minor, currency=currency, payment_method=PaymentMethod.CASH.value, source_entity_type="cash_movement", source_entity_id=str(movement.id), actor_user_id=actor.id, occurred_at=timestamp))
    append_audit(session, action=f"CASH_{kind}_RECORDED", entity_type="cash_movement", entity_id=str(movement.id), actor=actor, new_values={"business_day_id": day.id, "direction": direction, "amount_minor": amount_minor, "currency": currency}, reason=clean_reason, approver=actor if kind == "ADJUSTMENT" else None, correlation_id=key)
    session.add(IdempotencyRecord(namespace="cash_movement", request_key=key, response_json={"movement_id": movement.id}))
    session.flush()
    return movement, True


def reverse_cash_movement(session: Session, *, actor: User, movement_id: int, reason: str, idempotency_key: str, occurred_at: datetime | None = None) -> tuple[CashMovement, bool]:
    _require(session, actor, "cash.adjust")
    key = _validate_key(idempotency_key)
    existing = session.scalar(select(CashMovement).where(CashMovement.idempotency_key == key))
    if existing:
        return existing, False
    original = session.get(CashMovement, movement_id)
    if original is None or original.movement_type == "REVERSAL":
        raise ValueError("Original cash movement not found")
    prior = session.scalar(select(CashMovement).where(CashMovement.reversed_movement_id == original.id))
    if prior:
        return prior, False
    clean = reason.strip()
    if not clean:
        raise ValueError("A reversal reason is required")
    timestamp = occurred_at or utc_now()
    reversal = CashMovement(business_day_id=original.business_day_id, movement_type="REVERSAL", direction="OUTFLOW" if original.direction == "INFLOW" else "INFLOW", amount_minor=original.amount_minor, currency=original.currency, reason=clean, actor_user_id=actor.id, related_entity_type="cash_movement", related_entity_id=str(original.id), approved_by_user_id=actor.id, reversed_movement_id=original.id, idempotency_key=key, occurred_at=timestamp)
    session.add(reversal)
    session.flush()
    source_ledger = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_type == "cash_movement", LedgerEntry.source_entity_id == str(original.id)))
    session.add(LedgerEntry(business_day_id=original.business_day_id, entry_type="CASH_REVERSAL", direction=reversal.direction, amount_minor=reversal.amount_minor, currency=reversal.currency, payment_method="CASH", source_entity_type="cash_movement", source_entity_id=str(reversal.id), actor_user_id=actor.id, reverses_ledger_entry_id=source_ledger.id if source_ledger else None, occurred_at=timestamp))
    append_audit(session, action="CASH_MOVEMENT_REVERSED", entity_type="cash_movement", entity_id=str(original.id), actor=actor, new_values={"reversal_movement_id": reversal.id}, reason=clean, approver=actor, correlation_id=key)
    session.add(IdempotencyRecord(namespace="cash_reversal", request_key=key, response_json={"movement_id": reversal.id}))
    session.flush()
    return reversal, True


def record_retained_float(session: Session, *, actor: User, currency: str, amount_minor: int, reason: str, idempotency_key: str) -> tuple[RetainedFloat, bool]:
    _require(session, actor, "cash.owner_withdraw")
    key = _validate_key(idempotency_key)
    existing = session.scalar(select(RetainedFloat).where(RetainedFloat.idempotency_key == key))
    if existing:
        return existing, False
    if currency not in {"KHR", "USD"} or amount_minor < 0 or not reason.strip():
        raise ValueError("Valid currency, nonnegative amount, and reason are required")
    day = business_day_for_transaction(session)
    retained = RetainedFloat(business_day_id=day.id, currency=currency, amount_minor=amount_minor, reason=reason.strip(), actor_user_id=actor.id, idempotency_key=key)
    session.add(retained)
    session.flush()
    append_audit(session, action="RETAINED_FLOAT_RECORDED", entity_type="retained_float", entity_id=str(retained.id), actor=actor, new_values={"business_day_id": day.id, "currency": currency, "amount_minor": amount_minor, "automatic_carry": False}, reason=retained.reason, correlation_id=key)
    return retained, True


def suggested_retained_float(session: Session, *, currency: str, current_business_day_id: int) -> RetainedFloat | None:
    return session.scalar(select(RetainedFloat).where(RetainedFloat.currency == currency, RetainedFloat.business_day_id != current_business_day_id).order_by(RetainedFloat.created_at.desc(), RetainedFloat.id.desc()).limit(1))


def record_cash_count(session: Session, *, actor: User, actual_khr_minor: int, actual_usd_minor: int, idempotency_key: str, counted_at: datetime | None = None) -> tuple[CashCount, bool]:
    _require(session, actor, "cash.count")
    key = _validate_key(idempotency_key)
    existing = session.scalar(select(CashCount).where(CashCount.idempotency_key == key))
    if existing:
        return existing, False
    if actual_khr_minor < 0 or actual_usd_minor < 0:
        raise ValueError("Actual cash cannot be negative")
    day = business_day_for_transaction(session)
    expected_khr = _expected_for(session, day.id, "KHR", "CASH")
    expected_usd = _expected_for(session, day.id, "USD", "CASH")
    count = CashCount(business_day_id=day.id, actual_khr_minor=actual_khr_minor, actual_usd_minor=actual_usd_minor, expected_khr_minor=expected_khr, expected_usd_minor=expected_usd, difference_khr_minor=actual_khr_minor - expected_khr, difference_usd_minor=actual_usd_minor - expected_usd, counted_by_user_id=actor.id, counted_at=counted_at or utc_now(), idempotency_key=key)
    session.add(count)
    session.flush()
    append_audit(session, action="CASH_COUNT_RECORDED", entity_type="cash_count", entity_id=str(count.id), actor=actor, new_values={"business_day_id": day.id, "actual_khr_minor": actual_khr_minor, "actual_usd_minor": actual_usd_minor, "expected_khr_minor": expected_khr, "expected_usd_minor": expected_usd, "difference_khr_minor": count.difference_khr_minor, "difference_usd_minor": count.difference_usd_minor}, correlation_id=key)
    session.add(IdempotencyRecord(namespace="cash_count", request_key=key, response_json={"cash_count_id": count.id}))
    session.flush()
    return count, True


def cash_history(session: Session, *, actor: User, limit: int = 20) -> list[CashMovement]:
    _require(session, actor, "cash.view")
    day = business_day_for_transaction(session)
    return list(session.scalars(select(CashMovement).where(CashMovement.business_day_id == day.id).order_by(CashMovement.occurred_at.desc(), CashMovement.id.desc()).limit(min(max(limit, 1), 100))))
