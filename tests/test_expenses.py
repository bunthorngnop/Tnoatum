from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import AuditLog, Expense, ExpenseApprovalEvent, ExpenseCategory, ExpenseLimit, ExpenseRequest, ExpenseStatus, LedgerEntry, NotificationOutbox, Role, User, UserRole
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.expenses import AttachmentInput, approve_expense_request, ask_expense_question, expense_activity, record_expense_approval_opened, reject_expense_request, respond_to_expense_question, reverse_expense, submit_expense_request


@pytest.fixture
def expense_setup(session: Session, owner: User) -> dict:
    settings = Settings("Tnoat Tum Cafe", "Asia/Phnom_Penh", time(8), time(17), time(18), "sqlite:///:memory:", (owner.telegram_user_id,), ("KHR", "USD"), Path("backups"), 30)
    seed_foundation(session, settings)
    staff_role = session.scalar(select(Role).where(Role.code == "STAFF"))
    staff = User(telegram_user_id=700001, display_name="Expense Staff")
    session.add(staff)
    session.flush()
    session.add(UserRole(user_id=staff.id, role_id=staff_role.id))
    session.add_all([
        ExpenseLimit(role_id=staff_role.id, currency="KHR", amount_minor=10_000, created_by_user_id=owner.id),
        ExpenseLimit(role_id=staff_role.id, currency="USD", amount_minor=500, created_by_user_id=owner.id),
    ])
    category = session.scalar(select(ExpenseCategory).where(ExpenseCategory.code == "INGREDIENTS"))
    open_business_day(session, business_date=date(2026, 8, 29), actor=owner, opened_at=datetime.now(timezone.utc))
    session.commit()
    return {"owner": owner, "staff": staff, "category": category}


def _receipt() -> AttachmentInput:
    return AttachmentInput("telegram-file-id", "unique-receipt-1", "PHOTO", "image/jpeg", 12345, "receipts/test-safe-id.jpg")


def _submit(session: Session, setup: dict, *, amount: int = 5000, currency: str = "KHR", source: str = "KHR_CASH", key: str = "expense-1", auto: bool = True, receipt: bool = True, actor: User | None = None):
    return submit_expense_request(session, actor=actor or setup["staff"], category_id=setup["category"].id, amount_minor=amount, currency=currency, payment_source=source, reason="Buy ingredients", attachments=[_receipt()] if receipt else [], idempotency_key=key, within_limit_posts_immediately=auto, require_receipt_for_all=True)


def test_valid_khr_within_limit_expense_posts(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup)
    session.commit()
    assert result.expense is not None
    assert result.request.status == "APPROVED"
    assert (result.expense.amount_minor, result.expense.currency) == (5000, "KHR")


def test_valid_usd_expense_uses_exact_cents(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup, amount=250, currency="USD", source="USD_CASH", key="usd")
    session.commit()
    assert result.expense.amount_minor == 250
    assert result.expense.currency == "USD"


def test_cash_expense_ledger_uses_correct_currency(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup, amount=300, currency="USD", source="USD_CASH", key="usd-cash")
    session.commit()
    entry = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_type == "expense", LedgerEntry.source_entity_id == str(result.expense.id)))
    assert (entry.direction, entry.currency, entry.payment_method) == ("OUTFLOW", "USD", "CASH")


def test_aba_expense_remains_separate_from_drawer_cash(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup, source="ABA_KHQR", key="aba")
    session.commit()
    entry = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_id == str(result.expense.id)))
    assert entry.payment_method == "ABA_KHQR"


def test_within_limit_policy_can_keep_request_pending(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup, auto=False, key="policy-pending")
    session.commit()
    assert result.request.was_over_limit is False
    assert result.request.status == "PENDING"
    assert result.expense is None


def test_above_limit_becomes_pending_without_ledger(session: Session, expense_setup: dict) -> None:
    result = _submit(session, expense_setup, amount=10_001, key="over-limit")
    session.commit()
    assert result.request.was_over_limit is True
    assert result.request.status == "PENDING"
    assert session.query(Expense).count() == 0
    assert session.query(LedgerEntry).filter_by(entry_type="EXPENSE").count() == 0


def test_owner_approval_posts_exactly_once(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="pending-approve").request
    session.commit()
    first, created = approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="approve-1")
    session.commit()
    second, duplicate_created = approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="approve-1")
    assert first.id == second.id
    assert (created, duplicate_created) == (True, False)
    assert session.query(Expense).count() == 1
    assert session.query(LedgerEntry).filter_by(entry_type="EXPENSE").count() == 1


def test_stale_second_approval_is_harmless(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="pending-stale").request
    session.commit()
    first, _ = approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="approve-a")
    session.commit()
    second, created = approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="approve-b")
    assert first.id == second.id
    assert created is False


def test_rejection_posts_no_official_expense(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="pending-reject").request
    session.commit()
    rejected, created = reject_expense_request(session, actor=expense_setup["owner"], request_id=request.id, reason="Not authorized purchase", idempotency_key="reject-1")
    session.commit()
    assert created is True
    assert rejected.status == "REJECTED"
    assert session.query(Expense).count() == 0


def test_self_approval_is_prevented(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=1000, key="owner-request", auto=False, actor=expense_setup["owner"]).request
    session.commit()
    with pytest.raises(PermissionError, match="own pending"):
        approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="self-approve")


def test_unauthorized_approver_is_blocked(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="unauthorized").request
    session.commit()
    with pytest.raises(PermissionError, match="not authorized"):
        approve_expense_request(session, actor=expense_setup["staff"], request_id=request.id, idempotency_key="staff-approve")


def test_receipt_attachment_metadata_is_preserved(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, key="receipt").request
    session.commit()
    assert len(request.attachments) == 1
    attachment = request.attachments[0]
    assert (attachment.media_type, attachment.file_size, attachment.local_relative_path) == ("PHOTO", 12345, "receipts/test-safe-id.jpg")


def test_missing_required_receipt_is_rejected(session: Session, expense_setup: dict) -> None:
    with pytest.raises(ValueError, match="receipt is required"):
        _submit(session, expense_setup, key="missing-receipt", receipt=False)


def test_ask_question_keeps_pending_and_notifies_requester(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="question-request").request
    session.commit()
    questioned, created = ask_expense_question(session, actor=expense_setup["owner"], request_id=request.id, question="Which supplier?", idempotency_key="question-1")
    session.commit()
    assert created is True
    assert questioned.status == "PENDING"
    notification = session.scalar(select(NotificationOutbox).where(NotificationOutbox.notification_type == "EXPENSE_QUESTION"))
    assert notification.recipient_user_id == expense_setup["staff"].id


def test_requester_can_respond_and_request_stays_pending(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="response-request").request
    session.commit()
    ask_expense_question(session, actor=expense_setup["owner"], request_id=request.id, question="Which supplier?", idempotency_key="question-2")
    session.commit()
    responded, created = respond_to_expense_question(session, actor=expense_setup["staff"], request_id=request.id, response="Local market", idempotency_key="response-1")
    session.commit()
    assert created is True
    assert responded.status == "PENDING"
    assert session.query(ExpenseApprovalEvent).filter_by(event_type="REQUESTER_RESPONDED").count() == 1


def test_approval_creates_requester_notification(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="notify-request").request
    session.commit()
    approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="notify-approve")
    session.commit()
    notification = session.scalar(select(NotificationOutbox).where(NotificationOutbox.notification_type == "EXPENSE_APPROVED"))
    assert notification.recipient_user_id == expense_setup["staff"].id


def test_full_critical_audit_trail(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, amount=20_000, key="audit-request").request
    session.commit()
    record_expense_approval_opened(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="audit-opened")
    approve_expense_request(session, actor=expense_setup["owner"], request_id=request.id, idempotency_key="audit-approve")
    session.commit()
    actions = set(session.scalars(select(AuditLog.action).where(AuditLog.entity_type.in_(["expense_request", "expense"]))))
    assert {"EXPENSE_REQUEST_CREATED", "EXPENSE_RECEIPT_ATTACHED", "EXPENSE_REQUEST_SUBMITTED", "EXPENSE_APPROVAL_REQUESTED", "EXPENSE_APPROVER_OPENED", "EXPENSE_APPROVED", "EXPENSE_POSTED"}.issubset(actions)


def test_posted_expense_cannot_be_hard_deleted(session: Session, expense_setup: dict) -> None:
    expense = _submit(session, expense_setup, key="immutable").expense
    session.commit()
    session.delete(expense)
    with pytest.raises(ValueError, match="cannot be deleted"):
        session.commit()


def test_reversal_preserves_original_and_creates_inverse_ledger(session: Session, expense_setup: dict) -> None:
    expense = _submit(session, expense_setup, key="reverse-original").expense
    session.commit()
    reversed_expense, created = reverse_expense(session, actor=expense_setup["owner"], expense_id=expense.id, reason="Duplicate receipt", idempotency_key="reverse-expense")
    session.commit()
    assert created is True
    assert reversed_expense.status == ExpenseStatus.REVERSED.value
    assert session.query(Expense).count() == 1
    reversal = session.scalar(select(LedgerEntry).where(LedgerEntry.entry_type == "EXPENSE_REVERSAL"))
    assert reversal.direction == "INFLOW"
    assert reversal.amount_minor == expense.amount_minor


def test_staff_expense_view_is_scoped(session: Session, expense_setup: dict) -> None:
    request = _submit(session, expense_setup, key="view").request
    session.commit()
    assert [item.id for item in expense_activity(session, requester=expense_setup["staff"])] == [request.id]
    assert expense_activity(session, requester=expense_setup["owner"], staff_user_id=expense_setup["staff"].id)[0].id == request.id
    with pytest.raises(PermissionError, match="only their own"):
        expense_activity(session, requester=expense_setup["staff"], staff_user_id=expense_setup["owner"].id)
