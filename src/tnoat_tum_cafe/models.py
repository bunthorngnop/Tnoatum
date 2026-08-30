from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessDayStatus(StrEnum):
    OPEN = "OPEN"
    CLOSING_PENDING = "CLOSING_PENDING"
    CLOSED = "CLOSED"


class PricingMode(StrEnum):
    FIXED_PRICE = "FIXED_PRICE"
    OPEN_PRICE = "OPEN_PRICE"
    MANUAL_ITEM = "MANUAL_ITEM"


class Currency(StrEnum):
    KHR = "KHR"
    USD = "USD"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    ABA_KHQR = "ABA_KHQR"


class SaleStatus(StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ExpenseRequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExpenseStatus(StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ExpensePaymentSource(StrEnum):
    KHR_CASH = "KHR_CASH"
    USD_CASH = "USD_CASH"
    ABA_KHQR = "ABA_KHQR"


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120))
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    roles: Mapped[list[Role]] = relationship(secondary="user_roles")
    __table_args__ = (CheckConstraint("telegram_user_id > 0", name="ck_users_telegram_id_positive"),)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)


class UserPermissionOverride(Base):
    __tablename__ = "user_permission_overrides"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="RESTRICT"), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BusinessDay(Base):
    __tablename__ = "business_days"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, unique=True)
    status: Mapped[str] = mapped_column(String(24), default=BusinessDayStatus.OPEN.value)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    opened_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    closing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_started_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','CLOSING_PENDING','CLOSED')", name="ck_business_day_status"),
        Index("uq_one_active_business_day", text("1"), unique=True, sqlite_where=(status != "CLOSED")),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(80))
    request_key: Mapped[str] = mapped_column(String(160))
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (UniqueConstraint("namespace", "request_key", name="uq_idempotency_namespace_key"),)


class ProductCategory(Base):
    __tablename__ = "product_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    pricing_mode: Mapped[str] = mapped_column(String(24))
    fixed_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    fixed_price_currency: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    category: Mapped[ProductCategory] = relationship()
    __table_args__ = (
        CheckConstraint("pricing_mode IN ('FIXED_PRICE','OPEN_PRICE')", name="ck_product_pricing_mode"),
        CheckConstraint("fixed_price_minor IS NULL OR fixed_price_minor > 0", name="ck_product_price_positive"),
        CheckConstraint("fixed_price_currency IS NULL OR fixed_price_currency IN ('KHR','USD')", name="ck_product_currency"),
        CheckConstraint("(pricing_mode = 'FIXED_PRICE' AND fixed_price_minor IS NOT NULL AND fixed_price_currency IS NOT NULL) OR (pricing_mode = 'OPEN_PRICE' AND fixed_price_minor IS NULL AND fixed_price_currency IS NULL)", name="ck_product_price_by_mode"),
    )


class ProductSuggestedPrice(Base):
    __tablename__ = "product_suggested_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_suggested_price_positive"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_suggested_price_currency"),
        UniqueConstraint("product_id", "amount_minor", "currency", name="uq_product_suggested_price"),
    )


class DiscountRule(Base):
    __tablename__ = "discount_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    basis_points: Mapped[int] = mapped_column(Integer, unique=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("basis_points >= 0 AND basis_points <= 10000", name="ck_discount_basis_points"),)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_number: Mapped[str] = mapped_column(String(40), unique=True)
    business_day_id: Mapped[int] = mapped_column(ForeignKey("business_days.id", ondelete="RESTRICT"))
    staff_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default=SaleStatus.POSTED.value)
    currency: Mapped[str] = mapped_column(String(3))
    subtotal_minor: Mapped[int] = mapped_column(BigInteger)
    discount_basis_points: Mapped[int] = mapped_column(Integer, default=0)
    discount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list[SaleItem]] = relationship(back_populates="sale", order_by="SaleItem.id")
    payments: Mapped[list[SalePayment]] = relationship(back_populates="sale", order_by="SalePayment.id")
    __table_args__ = (
        CheckConstraint("status IN ('POSTED','REVERSED')", name="ck_sale_status"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_sale_currency"),
        CheckConstraint("subtotal_minor > 0 AND discount_minor >= 0 AND total_minor > 0", name="ck_sale_amounts_positive"),
        CheckConstraint("subtotal_minor - discount_minor = total_minor", name="ck_sale_total_math"),
        CheckConstraint("discount_basis_points >= 0 AND discount_basis_points <= 10000", name="ck_sale_discount_basis_points"),
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_code_snapshot: Mapped[str | None] = mapped_column(String(60))
    name_snapshot: Mapped[str] = mapped_column(String(160))
    pricing_mode_snapshot: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    sale: Mapped[Sale] = relationship(back_populates="items")
    __table_args__ = (
        CheckConstraint("pricing_mode_snapshot IN ('FIXED_PRICE','OPEN_PRICE','MANUAL_ITEM')", name="ck_sale_item_pricing_mode"),
        CheckConstraint("quantity > 0 AND unit_price_minor > 0 AND line_total_minor > 0", name="ck_sale_item_amounts"),
        CheckConstraint("line_total_minor = quantity * unit_price_minor", name="ck_sale_item_math"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_sale_item_currency"),
    )


class SalePayment(Base):
    __tablename__ = "sale_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    method: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    reverses_payment_id: Mapped[int | None] = mapped_column(ForeignKey("sale_payments.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sale: Mapped[Sale] = relationship(back_populates="payments", foreign_keys=[sale_id])
    __table_args__ = (
        CheckConstraint("method IN ('CASH','ABA_KHQR')", name="ck_sale_payment_method"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_sale_payment_currency"),
        CheckConstraint("amount_minor > 0", name="ck_sale_payment_amount"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_day_id: Mapped[int] = mapped_column(ForeignKey("business_days.id", ondelete="RESTRICT"))
    entry_type: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(12))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payment_method: Mapped[str] = mapped_column(String(20))
    source_entity_type: Mapped[str] = mapped_column(String(40))
    source_entity_id: Mapped[str] = mapped_column(String(80))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reverses_ledger_entry_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_entries.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        CheckConstraint("direction IN ('INFLOW','OUTFLOW')", name="ck_ledger_direction"),
        CheckConstraint("amount_minor > 0", name="ck_ledger_amount"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_ledger_currency"),
        CheckConstraint("payment_method IN ('CASH','ABA_KHQR')", name="ck_ledger_payment_method"),
        Index("ix_ledger_business_day_currency", "business_day_id", "currency"),
    )


class SaleCorrection(Base):
    __tablename__ = "sale_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"), unique=True)
    replacement_sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str | None] = mapped_column(String(16))
    receipt_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ExpenseLimit(Base):
    __tablename__ = "expense_limits"
    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (
        CheckConstraint("currency IN ('KHR','USD')", name="ck_expense_limit_currency"),
        CheckConstraint("amount_minor >= 0", name="ck_expense_limit_amount"),
        CheckConstraint("(role_id IS NOT NULL AND user_id IS NULL) OR (role_id IS NULL AND user_id IS NOT NULL)", name="ck_expense_limit_scope"),
        UniqueConstraint("role_id", "currency", name="uq_expense_limit_role_currency"),
        UniqueConstraint("user_id", "currency", name="uq_expense_limit_user_currency"),
    )


class ExpenseRequest(Base):
    __tablename__ = "expense_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_number: Mapped[str] = mapped_column(String(40), unique=True)
    business_day_id: Mapped[int] = mapped_column(ForeignKey("business_days.id", ondelete="RESTRICT"))
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id", ondelete="RESTRICT"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payment_source: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=ExpenseRequestStatus.PENDING.value)
    authority_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    was_over_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_required_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    category: Mapped[ExpenseCategory] = relationship()
    attachments: Mapped[list[ExpenseAttachment]] = relationship(back_populates="request", order_by="ExpenseAttachment.id")
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_expense_request_amount"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_expense_request_currency"),
        CheckConstraint("payment_source IN ('KHR_CASH','USD_CASH','ABA_KHQR')", name="ck_expense_request_source"),
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_expense_request_status"),
        CheckConstraint("authority_limit_minor IS NULL OR authority_limit_minor >= 0", name="ck_expense_request_limit"),
    )


class ExpenseAttachment(Base):
    __tablename__ = "expense_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_request_id: Mapped[int] = mapped_column(ForeignKey("expense_requests.id", ondelete="RESTRICT"))
    telegram_file_id: Mapped[str] = mapped_column(String(255))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    local_relative_path: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    request: Mapped[ExpenseRequest] = relationship(back_populates="attachments")
    __table_args__ = (
        CheckConstraint("media_type IN ('PHOTO','DOCUMENT')", name="ck_expense_attachment_media_type"),
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="ck_expense_attachment_size"),
    )


class ExpenseApprovalEvent(Base):
    __tablename__ = "expense_approval_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_request_id: Mapped[int] = mapped_column(ForeignKey("expense_requests.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(40))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    message: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    __table_args__ = (UniqueConstraint("event_type", "correlation_id", name="uq_expense_event_idempotency"),)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_number: Mapped[str] = mapped_column(String(40), unique=True)
    expense_request_id: Mapped[int] = mapped_column(ForeignKey("expense_requests.id", ondelete="RESTRICT"), unique=True)
    business_day_id: Mapped[int] = mapped_column(ForeignKey("business_days.id", ondelete="RESTRICT"))
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id", ondelete="RESTRICT"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payment_source: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=ExpenseStatus.POSTED.value)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    posted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_expense_amount"),
        CheckConstraint("currency IN ('KHR','USD')", name="ck_expense_currency"),
        CheckConstraint("payment_source IN ('KHR_CASH','USD_CASH','ABA_KHQR')", name="ck_expense_source"),
        CheckConstraint("status IN ('POSTED','REVERSED')", name="ck_expense_status"),
    )


class ExpenseCorrection(Base):
    __tablename__ = "expense_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id", ondelete="RESTRICT"), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    notification_type: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _prevent_audit_mutation(_mapper, _connection, _target) -> None:
    raise ValueError("Audit records are append-only")


def _prevent_financial_delete(_mapper, _connection, _target) -> None:
    raise ValueError("Posted financial records cannot be deleted")


def _prevent_financial_detail_update(_mapper, _connection, _target) -> None:
    raise ValueError("Posted financial details are immutable; use a reversal")


for _immutable_detail in (SaleItem, SalePayment, LedgerEntry, SaleCorrection, ExpenseAttachment, ExpenseApprovalEvent, ExpenseCorrection):
    event.listen(_immutable_detail, "before_update", _prevent_financial_detail_update)
    event.listen(_immutable_detail, "before_delete", _prevent_financial_delete)
event.listen(Sale, "before_delete", _prevent_financial_delete)
event.listen(Expense, "before_delete", _prevent_financial_delete)
