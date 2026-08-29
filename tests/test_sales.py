from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import AuditLog, DiscountRule, LedgerEntry, PaymentMethod, PricingMode, Product, ProductCategory, Role, Sale, SaleItem, SalePayment, SaleStatus, User, UserRole
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.sales import CartItemInput, PaymentInput, post_sale, reverse_sale, staff_activity


@pytest.fixture
def sales_setup(session: Session, owner: User) -> dict:
    settings = Settings("Tnoat Tum Cafe", "Asia/Phnom_Penh", time(8), time(17), time(18), "sqlite:///:memory:", (owner.telegram_user_id,), ("KHR", "USD"), Path("backups"), 30)
    seed_foundation(session, settings)
    category = ProductCategory(code="TEST", name="Test", icon="☕")
    session.add(category)
    session.flush()
    fixed_khr = Product(category_id=category.id, code="FIXED_KHR", name="Fixed KHR", pricing_mode=PricingMode.FIXED_PRICE.value, fixed_price_minor=4000, fixed_price_currency="KHR")
    fixed_usd = Product(category_id=category.id, code="FIXED_USD", name="Fixed USD", pricing_mode=PricingMode.FIXED_PRICE.value, fixed_price_minor=250, fixed_price_currency="USD")
    open_product = Product(category_id=category.id, code="OPEN", name="Open Food", pricing_mode=PricingMode.OPEN_PRICE.value)
    session.add_all([fixed_khr, fixed_usd, open_product, DiscountRule(name="10% test", basis_points=1000)])
    session.flush()
    open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=datetime.now(timezone.utc))
    session.commit()
    return {"owner": owner, "fixed_khr": fixed_khr, "fixed_usd": fixed_usd, "open": open_product}


def _post(session: Session, setup: dict, items: list[CartItemInput], payments: list[PaymentInput], *, discount: int = 0, key: str = "test") -> Sale:
    sale, created = post_sale(session, actor=setup["owner"], items=items, discount_basis_points=discount, payments=payments, idempotency_key=key)
    assert created is True
    session.commit()
    return sale


def test_fixed_price_khr_cash_sale(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], [PaymentInput("CASH", "KHR", 4000)])
    assert (sale.currency, sale.subtotal_minor, sale.total_minor) == ("KHR", 4000, 4000)
    assert session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_type == "sale_payment")).payment_method == "CASH"


def test_open_price_sale(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["open"].id, quantity=1, unit_price_minor=7500, manual_currency="KHR")], [PaymentInput("CASH", "KHR", 7500)], key="open")
    assert sale.items[0].pricing_mode_snapshot == "OPEN_PRICE"
    assert sale.items[0].unit_price_minor == 7500


def test_manual_custom_item(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(quantity=1, unit_price_minor=6000, manual_name="Special Khmer dish", manual_currency="KHR")], [PaymentInput("CASH", "KHR", 6000)], key="manual")
    assert sale.items[0].product_id is None
    assert sale.items[0].pricing_mode_snapshot == "MANUAL_ITEM"


def test_multi_item_quantity_and_discount(session: Session, sales_setup: dict) -> None:
    items = [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=2), CartItemInput(product_id=sales_setup["open"].id, quantity=1, unit_price_minor=2000, manual_currency="KHR")]
    sale = _post(session, sales_setup, items, [PaymentInput("CASH", "KHR", 9000)], discount=1000, key="cart")
    assert sale.subtotal_minor == 10000
    assert sale.discount_minor == 1000
    assert sale.total_minor == 9000
    assert [item.quantity for item in sale.items] == [2, 1]


def test_owner_custom_discount_uses_exact_basis_points(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_usd"].id, quantity=2)], [PaymentInput("CASH", "USD", 437)], discount=1250, key="custom-discount")
    assert (sale.subtotal_minor, sale.discount_minor, sale.total_minor) == (500, 63, 437)


def test_usd_cash_uses_exact_cents(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_usd"].id, quantity=2)], [PaymentInput("CASH", "USD", 500)], key="usd")
    assert sale.total_minor == 500


def test_aba_sale_is_separate_from_cash(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], [PaymentInput("ABA_KHQR", "KHR", 4000)], key="aba")
    entry = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_id == str(sale.payments[0].id)))
    assert entry.payment_method == PaymentMethod.ABA_KHQR.value


def test_same_currency_split_payment_exactly_matches(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], [PaymentInput("CASH", "KHR", 1500), PaymentInput("ABA_KHQR", "KHR", 2500)], key="split")
    assert {(payment.method, payment.amount_minor) for payment in sale.payments} == {("CASH", 1500), ("ABA_KHQR", 2500)}


def test_cross_currency_or_inexact_payment_is_rejected(session: Session, sales_setup: dict) -> None:
    item = [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)]
    with pytest.raises(ValueError, match="cross-currency"):
        post_sale(session, actor=sales_setup["owner"], items=item, discount_basis_points=0, payments=[PaymentInput("CASH", "USD", 100)], idempotency_key="bad-currency")
    with pytest.raises(ValueError, match="exactly equal"):
        post_sale(session, actor=sales_setup["owner"], items=item, discount_basis_points=0, payments=[PaymentInput("CASH", "KHR", 3999)], idempotency_key="bad-total")


def test_duplicate_update_returns_same_sale_without_duplicate_posting(session: Session, sales_setup: dict) -> None:
    item = [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)]
    payment = [PaymentInput("CASH", "KHR", 4000)]
    first, created_first = post_sale(session, actor=sales_setup["owner"], items=item, discount_basis_points=0, payments=payment, idempotency_key="telegram-123")
    session.commit()
    second, created_second = post_sale(session, actor=sales_setup["owner"], items=item, discount_basis_points=0, payments=payment, idempotency_key="telegram-123")
    assert first.id == second.id
    assert (created_first, created_second) == (True, False)
    assert session.query(Sale).count() == 1


def test_historical_price_is_preserved_after_product_change(session: Session, sales_setup: dict) -> None:
    product = sales_setup["fixed_khr"]
    sale = _post(session, sales_setup, [CartItemInput(product_id=product.id, quantity=1)], [PaymentInput("CASH", "KHR", 4000)], key="history")
    product.fixed_price_minor = 5000
    session.commit()
    item = session.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
    assert item.unit_price_minor == 4000
    assert item.name_snapshot == "Fixed KHR"


def test_unauthorized_user_is_blocked(session: Session, sales_setup: dict) -> None:
    stranger = User(telegram_user_id=444, display_name="Unauthorized")
    session.add(stranger)
    session.commit()
    with pytest.raises(PermissionError, match="not authorized"):
        post_sale(session, actor=stranger, items=[CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], discount_basis_points=0, payments=[PaymentInput("CASH", "KHR", 4000)], idempotency_key="blocked")


def test_staff_account_is_scoped_to_requester(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], [PaymentInput("CASH", "KHR", 4000)], key="account")
    staff_role = session.scalar(select(Role).where(Role.code == "STAFF"))
    other = User(telegram_user_id=555, display_name="Other Staff")
    session.add(other)
    session.flush()
    session.add(UserRole(user_id=other.id, role_id=staff_role.id))
    session.commit()
    assert [item.id for item in staff_activity(session, requester=sales_setup["owner"])] == [sale.id]
    assert staff_activity(session, requester=other) == []
    with pytest.raises(PermissionError, match="only their own"):
        staff_activity(session, requester=other, staff_user_id=sales_setup["owner"].id)


def test_reversal_preserves_original_and_creates_audit_and_outflow(session: Session, sales_setup: dict) -> None:
    sale = _post(session, sales_setup, [CartItemInput(product_id=sales_setup["fixed_khr"].id, quantity=1)], [PaymentInput("CASH", "KHR", 4000)], key="original")
    reversed_sale, created = reverse_sale(session, actor=sales_setup["owner"], sale_id=sale.id, reason="Wrong item selected", idempotency_key="reverse-1")
    session.commit()
    assert created is True
    assert reversed_sale.status == SaleStatus.REVERSED.value
    assert session.query(SaleItem).filter_by(sale_id=sale.id).count() == 1
    assert session.query(SalePayment).filter_by(sale_id=sale.id).count() == 2
    assert session.query(LedgerEntry).filter_by(direction="OUTFLOW", entry_type="SALE_REVERSAL").count() == 1
    assert session.query(AuditLog).filter_by(action="SALE_REVERSED", entity_id=str(sale.id)).count() == 1
