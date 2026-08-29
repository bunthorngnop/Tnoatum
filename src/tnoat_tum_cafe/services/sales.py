from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import AuditLog, BusinessDayStatus, Currency, DiscountRule, IdempotencyRecord, LedgerEntry, PaymentMethod, PricingMode, Product, Sale, SaleCorrection, SaleItem, SalePayment, SaleStatus, User, utc_now
from .audit import append_audit
from .auth import has_permission
from .business_days import business_day_for_transaction
from .money import discount_amount


@dataclass(frozen=True)
class CartItemInput:
    quantity: int
    unit_price_minor: int | None = None
    product_id: int | None = None
    manual_name: str | None = None
    manual_currency: str | None = None


@dataclass(frozen=True)
class PaymentInput:
    method: str
    currency: str
    amount_minor: int


def preview_sale(session: Session, *, items: list[CartItemInput], discount_basis_points: int) -> tuple[str, int, int, int]:
    if not items:
        raise ValueError("Cart cannot be empty")
    resolved = [_resolve_item(session, item) for item in items]
    currencies = {item["currency"] for item in resolved}
    if len(currencies) != 1:
        raise ValueError("One sale cannot mix KHR and USD items")
    subtotal = sum(item["unit"] * source.quantity for item, source in zip(resolved, items, strict=True))
    discount = discount_amount(subtotal, discount_basis_points)
    return currencies.pop(), subtotal, discount, subtotal - discount


def _resolve_item(session: Session, item: CartItemInput) -> dict:
    if not 1 <= item.quantity <= 999:
        raise ValueError("Quantity must be between 1 and 999")
    if item.product_id is None:
        name = (item.manual_name or "").strip()
        if not name or len(name) > 160 or item.manual_currency not in {"KHR", "USD"} or not item.unit_price_minor:
            raise ValueError("Manual item requires name, currency, and positive price")
        return {"product": None, "code": None, "name": name, "mode": PricingMode.MANUAL_ITEM.value, "currency": item.manual_currency, "unit": item.unit_price_minor}
    product = session.get(Product, item.product_id)
    if product is None or not product.is_active:
        raise ValueError("Product is unavailable")
    if product.pricing_mode == PricingMode.FIXED_PRICE.value:
        if item.unit_price_minor is not None:
            raise ValueError("Fixed-price products use the configured official price")
        unit, currency = product.fixed_price_minor, product.fixed_price_currency
    else:
        if not item.unit_price_minor or item.unit_price_minor <= 0 or item.manual_currency not in {"KHR", "USD"}:
            raise ValueError("Open-price products require a positive price and currency")
        unit, currency = item.unit_price_minor, item.manual_currency
    return {"product": product, "code": product.code, "name": product.name, "mode": product.pricing_mode, "currency": currency, "unit": unit}


def post_sale(session: Session, *, actor: User, items: list[CartItemInput], discount_basis_points: int, payments: list[PaymentInput], idempotency_key: str, posted_at: datetime | None = None) -> tuple[Sale, bool]:
    if not actor.is_active or not has_permission(session, actor, "sale.create"):
        raise PermissionError("User is not authorized to create sales")
    if not idempotency_key.strip() or len(idempotency_key) > 160:
        raise ValueError("A valid idempotency key is required")
    existing = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.namespace == "post_sale", IdempotencyRecord.request_key == idempotency_key))
    if existing:
        sale = session.get(Sale, int(existing.response_json["sale_id"]))
        return sale, False
    day = business_day_for_transaction(session)
    if day.status != BusinessDayStatus.OPEN.value:
        raise ValueError("Sales require an OPEN business day")
    if not items:
        raise ValueError("Cart cannot be empty")
    resolved = [_resolve_item(session, item) for item in items]
    currencies = {item["currency"] for item in resolved}
    if len(currencies) != 1:
        raise ValueError("One sale cannot mix KHR and USD items without an exchange-rate policy")
    currency = currencies.pop()
    subtotal = sum(item["unit"] * source.quantity for item, source in zip(resolved, items, strict=True))
    rule = session.scalar(select(DiscountRule).where(DiscountRule.basis_points == discount_basis_points, DiscountRule.is_active.is_(True)))
    if rule is None and not has_permission(session, actor, "sale.discount.custom"):
        raise ValueError("Discount is not configured")
    if rule is not None and rule.requires_approval:
        raise PermissionError("This discount requires an approval workflow not enabled in Phase 1")
    discount = discount_amount(subtotal, discount_basis_points)
    total = subtotal - discount
    if total <= 0:
        raise ValueError("Discount cannot reduce a sale to zero")
    if not payments or any(payment.currency != currency for payment in payments):
        raise ValueError("Payments must use the sale currency; cross-currency split is disabled")
    if any(payment.method not in {item.value for item in PaymentMethod} or payment.amount_minor <= 0 for payment in payments):
        raise ValueError("Invalid payment allocation")
    if sum(payment.amount_minor for payment in payments) != total:
        raise ValueError("Payment allocations must exactly equal amount due")
    timestamp = posted_at or utc_now()
    sale = Sale(receipt_number=f"TT-{day.business_date:%Y%m%d}-{uuid4().hex[:10].upper()}", business_day_id=day.id, staff_user_id=actor.id, status=SaleStatus.POSTED.value, currency=currency, subtotal_minor=subtotal, discount_basis_points=discount_basis_points, discount_minor=discount, total_minor=total, posted_at=timestamp)
    session.add(sale)
    session.flush()
    for source, item in zip(items, resolved, strict=True):
        session.add(SaleItem(sale_id=sale.id, product_id=item["product"].id if item["product"] else None, product_code_snapshot=item["code"], name_snapshot=item["name"], pricing_mode_snapshot=item["mode"], quantity=source.quantity, unit_price_minor=item["unit"], currency=currency, line_total_minor=item["unit"] * source.quantity))
    for allocation in payments:
        payment = SalePayment(sale_id=sale.id, method=allocation.method, currency=currency, amount_minor=allocation.amount_minor, created_at=timestamp)
        session.add(payment)
        session.flush()
        session.add(LedgerEntry(business_day_id=day.id, entry_type="SALE_RECEIPT", direction="INFLOW", amount_minor=allocation.amount_minor, currency=currency, payment_method=allocation.method, source_entity_type="sale_payment", source_entity_id=str(payment.id), actor_user_id=actor.id, occurred_at=timestamp))
    session.add(IdempotencyRecord(namespace="post_sale", request_key=idempotency_key, response_json={"sale_id": sale.id}))
    append_audit(session, action="SALE_POSTED", entity_type="sale", entity_id=str(sale.id), actor=actor, new_values={"receipt_number": sale.receipt_number, "currency": currency, "subtotal_minor": subtotal, "discount_basis_points": discount_basis_points, "discount_minor": discount, "total_minor": total, "payment_methods": [payment.method for payment in payments]}, correlation_id=idempotency_key)
    session.flush()
    return sale, True


def reverse_sale(session: Session, *, actor: User, sale_id: int, reason: str, idempotency_key: str, replacement_sale_id: int | None = None, occurred_at: datetime | None = None) -> tuple[Sale, bool]:
    if not actor.is_active or not has_permission(session, actor, "sale.correct"):
        raise PermissionError("User is not authorized to correct sales")
    if not reason.strip():
        raise ValueError("A correction reason is required")
    existing = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.namespace == "reverse_sale", IdempotencyRecord.request_key == idempotency_key))
    if existing:
        return session.get(Sale, int(existing.response_json["sale_id"])), False
    sale = session.scalar(select(Sale).options(selectinload(Sale.payments)).where(Sale.id == sale_id))
    if sale is None:
        raise ValueError("Sale not found")
    if sale.staff_user_id != actor.id and not has_permission(session, actor, "reports.view_all"):
        raise PermissionError("Staff can correct only their own sale")
    if sale.status != SaleStatus.POSTED.value:
        raise ValueError("Sale is already reversed")
    timestamp = occurred_at or utc_now()
    sale.status = SaleStatus.REVERSED.value
    sale.reversed_at = timestamp
    sale.reversed_by_user_id = actor.id
    sale.reversal_reason = reason.strip()
    session.add(SaleCorrection(original_sale_id=sale.id, replacement_sale_id=replacement_sale_id, reason=reason.strip(), actor_user_id=actor.id, created_at=timestamp))
    original_ledger = list(session.scalars(select(LedgerEntry).where(LedgerEntry.source_entity_type == "sale_payment", LedgerEntry.source_entity_id.in_([str(payment.id) for payment in sale.payments]), LedgerEntry.direction == "INFLOW")))
    ledger_by_payment = {entry.source_entity_id: entry for entry in original_ledger}
    for payment in [item for item in sale.payments if not item.is_reversal]:
        reversal = SalePayment(sale_id=sale.id, method=payment.method, currency=payment.currency, amount_minor=payment.amount_minor, is_reversal=True, reverses_payment_id=payment.id, created_at=timestamp)
        session.add(reversal)
        original_entry = ledger_by_payment.get(str(payment.id))
        session.add(LedgerEntry(business_day_id=sale.business_day_id, entry_type="SALE_REVERSAL", direction="OUTFLOW", amount_minor=payment.amount_minor, currency=payment.currency, payment_method=payment.method, source_entity_type="sale_reversal", source_entity_id=str(sale.id), actor_user_id=actor.id, reverses_ledger_entry_id=original_entry.id if original_entry else None, occurred_at=timestamp))
    session.add(IdempotencyRecord(namespace="reverse_sale", request_key=idempotency_key, response_json={"sale_id": sale.id}))
    append_audit(session, action="SALE_REVERSED", entity_type="sale", entity_id=str(sale.id), actor=actor, old_values={"status": "POSTED"}, new_values={"status": "REVERSED", "replacement_sale_id": replacement_sale_id}, reason=reason.strip(), correlation_id=idempotency_key)
    session.flush()
    return sale, True


def staff_activity(session: Session, *, requester: User, staff_user_id: int | None = None, limit: int = 20) -> list[Sale]:
    target = staff_user_id or requester.id
    if target != requester.id and not has_permission(session, requester, "reports.view_all"):
        raise PermissionError("Staff may view only their own activity")
    return list(session.scalars(select(Sale).options(selectinload(Sale.items), selectinload(Sale.payments)).where(Sale.staff_user_id == target).order_by(Sale.posted_at.desc()).limit(min(max(limit, 1), 100))))
