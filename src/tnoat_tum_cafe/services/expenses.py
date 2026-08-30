from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..models import AuditLog, BusinessDayStatus, Expense, ExpenseApprovalEvent, ExpenseAttachment, ExpenseCategory, ExpenseCorrection, ExpenseLimit, ExpensePaymentSource, ExpenseRequest, ExpenseRequestStatus, ExpenseStatus, IdempotencyRecord, LedgerEntry, NotificationOutbox, Permission, RolePermission, User, UserPermissionOverride, UserRole, utc_now
from .audit import append_audit
from .auth import has_permission
from .business_days import business_day_for_transaction
from .money import format_money


@dataclass(frozen=True)
class AttachmentInput:
    telegram_file_id: str
    telegram_file_unique_id: str | None
    media_type: str
    mime_type: str | None = None
    file_size: int | None = None
    local_relative_path: str | None = None


@dataclass(frozen=True)
class ExpenseSubmissionResult:
    request: ExpenseRequest
    expense: Expense | None
    created: bool


def _payment_method(payment_source: str) -> str:
    return "ABA_KHQR" if payment_source == ExpensePaymentSource.ABA_KHQR.value else "CASH"


def _validate_source(currency: str, payment_source: str) -> None:
    if currency not in {"KHR", "USD"}:
        raise ValueError("Unsupported expense currency")
    allowed = {ExpensePaymentSource.ABA_KHQR.value, f"{currency}_CASH"}
    if payment_source not in allowed:
        raise ValueError("Payment source does not match the expense currency")


def authority_limit(session: Session, *, user: User, currency: str) -> int | None:
    direct = session.scalar(select(ExpenseLimit.amount_minor).where(ExpenseLimit.user_id == user.id, ExpenseLimit.currency == currency, ExpenseLimit.is_active.is_(True)))
    if direct is not None:
        return direct
    role_limits = list(session.scalars(select(ExpenseLimit.amount_minor).join(UserRole, UserRole.role_id == ExpenseLimit.role_id).where(UserRole.user_id == user.id, ExpenseLimit.currency == currency, ExpenseLimit.is_active.is_(True))))
    return min(role_limits) if role_limits else None


def _authorized_approvers(session: Session, requester_id: int) -> list[User]:
    permission = session.scalar(select(Permission).where(Permission.code == "expense.approve"))
    if permission is None:
        return []
    candidates = list(session.scalars(select(User).where(User.is_active.is_(True), User.id != requester_id)))
    return [user for user in candidates if has_permission(session, user, "expense.approve")]


def _enqueue(session: Session, *, recipient: User, notification_type: str, entity_type: str, entity_id: str, message: str) -> NotificationOutbox:
    notification = NotificationOutbox(recipient_user_id=recipient.id, notification_type=notification_type, entity_type=entity_type, entity_id=entity_id, message=message)
    session.add(notification)
    return notification


def _approval_summary(request: ExpenseRequest, requester: User, category: ExpenseCategory) -> str:
    limit_text = "NOT CONFIGURED" if request.authority_limit_minor is None else format_money(request.authority_limit_minor, request.currency)
    roles = ", ".join(sorted(role.code for role in requester.roles)) or "NO ROLE"
    return (f"💸 EXPENSE APPROVAL {request.request_number}\nRequester: {requester.display_name}\nTelegram ID: {requester.telegram_user_id}\nRole(s): {roles}\nSubmitted: {request.submitted_at.isoformat()}\nCategory: {category.name}\nAmount: {format_money(request.amount_minor, request.currency)}\nCurrency: {request.currency}\nPayment: {request.payment_source}\nReason: {request.reason}\nReceipt: {'YES' if request.attachments else 'NO'}\nAuthority limit: {limit_text}\nStatus: {request.status}")


def _post_expense(session: Session, *, request: ExpenseRequest, posting_actor: User, timestamp: datetime, correlation_id: str) -> Expense:
    existing = session.scalar(select(Expense).where(Expense.expense_request_id == request.id))
    if existing is not None:
        return existing
    expense = Expense(expense_number=f"EX-{request.request_number.removeprefix('ER-')}", expense_request_id=request.id, business_day_id=request.business_day_id, requester_user_id=request.requester_user_id, category_id=request.category_id, amount_minor=request.amount_minor, currency=request.currency, payment_source=request.payment_source, reason=request.reason, posted_at=timestamp, posted_by_user_id=posting_actor.id)
    session.add(expense)
    session.flush()
    session.add(LedgerEntry(business_day_id=request.business_day_id, entry_type="EXPENSE", direction="OUTFLOW", amount_minor=request.amount_minor, currency=request.currency, payment_method=_payment_method(request.payment_source), source_entity_type="expense", source_entity_id=str(expense.id), actor_user_id=posting_actor.id, occurred_at=timestamp))
    append_audit(session, action="EXPENSE_POSTED", entity_type="expense", entity_id=str(expense.id), actor=posting_actor, new_values={"request_id": request.id, "amount_minor": request.amount_minor, "currency": request.currency, "payment_source": request.payment_source}, correlation_id=correlation_id)
    return expense


def submit_expense_request(session: Session, *, actor: User, category_id: int, amount_minor: int, currency: str, payment_source: str, reason: str, attachments: list[AttachmentInput], idempotency_key: str, within_limit_posts_immediately: bool, require_receipt_for_all: bool, submitted_at: datetime | None = None) -> ExpenseSubmissionResult:
    if not actor.is_active or not has_permission(session, actor, "expense.create"):
        raise PermissionError("User is not authorized to create expenses")
    if not idempotency_key.strip() or len(idempotency_key) > 160:
        raise ValueError("A valid idempotency key is required")
    existing_key = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.namespace == "submit_expense", IdempotencyRecord.request_key == idempotency_key))
    if existing_key:
        request = session.get(ExpenseRequest, int(existing_key.response_json["request_id"]))
        expense = session.scalar(select(Expense).where(Expense.expense_request_id == request.id))
        return ExpenseSubmissionResult(request, expense, False)
    day = business_day_for_transaction(session)
    if day.status != BusinessDayStatus.OPEN.value:
        raise ValueError("Expenses require an OPEN business day")
    category = session.get(ExpenseCategory, category_id)
    if category is None or not category.is_active:
        raise ValueError("Expense category is unavailable")
    if amount_minor <= 0:
        raise ValueError("Expense amount must be positive")
    _validate_source(currency, payment_source)
    clean_reason = reason.strip()
    if not clean_reason or len(clean_reason) > 1000:
        raise ValueError("Expense reason must contain 1–1000 characters")
    receipt_required = require_receipt_for_all or category.receipt_required
    if receipt_required and not attachments:
        raise ValueError("A receipt is required for this expense")
    for attachment in attachments:
        if not attachment.telegram_file_id or attachment.media_type not in {"PHOTO", "DOCUMENT"} or (attachment.file_size is not None and attachment.file_size < 0):
            raise ValueError("Invalid receipt attachment metadata")
    timestamp = submitted_at or utc_now()
    limit = authority_limit(session, user=actor, currency=currency)
    over_limit = limit is None or amount_minor > limit
    request = ExpenseRequest(request_number=f"ER-{day.business_date:%Y%m%d}-{uuid4().hex[:10].upper()}", business_day_id=day.id, requester_user_id=actor.id, category_id=category.id, amount_minor=amount_minor, currency=currency, payment_source=payment_source, reason=clean_reason, status=ExpenseRequestStatus.PENDING.value, authority_limit_minor=limit, was_over_limit=over_limit, receipt_required_snapshot=receipt_required, submitted_at=timestamp)
    session.add(request)
    session.flush()
    append_audit(session, action="EXPENSE_REQUEST_CREATED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"request_number": request.request_number, "amount_minor": amount_minor, "currency": currency, "payment_source": payment_source, "category_id": category.id}, correlation_id=idempotency_key)
    for attachment in attachments:
        session.add(ExpenseAttachment(expense_request_id=request.id, telegram_file_id=attachment.telegram_file_id, telegram_file_unique_id=attachment.telegram_file_unique_id, media_type=attachment.media_type, mime_type=attachment.mime_type, file_size=attachment.file_size, local_relative_path=attachment.local_relative_path, created_at=timestamp))
        append_audit(session, action="EXPENSE_RECEIPT_ATTACHED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"media_type": attachment.media_type, "file_size": attachment.file_size}, correlation_id=f"{idempotency_key}:attachment:{attachment.telegram_file_unique_id or attachment.telegram_file_id}")
    session.flush()
    append_audit(session, action="EXPENSE_REQUEST_SUBMITTED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"status": "PENDING", "authority_limit_minor": limit, "was_over_limit": over_limit}, correlation_id=f"{idempotency_key}:submitted")
    expense = None
    if not over_limit and within_limit_posts_immediately:
        request.status = ExpenseRequestStatus.APPROVED.value
        request.decided_at = timestamp
        request.decided_by_user_id = actor.id
        request.decision_reason = "Posted automatically within configured authority"
        session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="AUTO_POSTED_WITHIN_LIMIT", actor_user_id=actor.id, message=request.decision_reason, correlation_id=f"{idempotency_key}:auto", created_at=timestamp))
        expense = _post_expense(session, request=request, posting_actor=actor, timestamp=timestamp, correlation_id=f"{idempotency_key}:posted")
        append_audit(session, action="EXPENSE_WITHIN_LIMIT_POSTED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"status": "APPROVED", "expense_id": expense.id}, correlation_id=f"{idempotency_key}:auto-decision")
    else:
        session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="APPROVAL_REQUESTED", actor_user_id=actor.id, message=None, correlation_id=f"{idempotency_key}:approval-requested", created_at=timestamp))
        approvers = _authorized_approvers(session, actor.id)
        for approver in approvers:
            _enqueue(session, recipient=approver, notification_type="EXPENSE_APPROVAL_REQUEST", entity_type="expense_request", entity_id=str(request.id), message=_approval_summary(request, actor, category))
        append_audit(session, action="EXPENSE_APPROVAL_REQUESTED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"approver_count": len(approvers)}, correlation_id=f"{idempotency_key}:approvers")
    session.add(IdempotencyRecord(namespace="submit_expense", request_key=idempotency_key, response_json={"request_id": request.id}))
    session.flush()
    return ExpenseSubmissionResult(request, expense, True)


def approve_expense_request(session: Session, *, actor: User, request_id: int, idempotency_key: str, occurred_at: datetime | None = None) -> tuple[Expense, bool]:
    if not actor.is_active or not has_permission(session, actor, "expense.approve"):
        raise PermissionError("User is not authorized to approve expenses")
    existing_key = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.namespace == "approve_expense", IdempotencyRecord.request_key == idempotency_key))
    if existing_key:
        return session.get(Expense, int(existing_key.response_json["expense_id"])), False
    request = session.get(ExpenseRequest, request_id)
    if request is None:
        raise ValueError("Expense request not found")
    if request.requester_user_id == actor.id:
        raise PermissionError("Requester cannot approve their own pending expense")
    existing_expense = session.scalar(select(Expense).where(Expense.expense_request_id == request.id))
    if request.status == ExpenseRequestStatus.APPROVED.value and existing_expense:
        return existing_expense, False
    if request.status != ExpenseRequestStatus.PENDING.value:
        raise ValueError("Expense request already has a terminal decision")
    timestamp = occurred_at or utc_now()
    decision = session.execute(update(ExpenseRequest).where(ExpenseRequest.id == request.id, ExpenseRequest.status == ExpenseRequestStatus.PENDING.value).values(status=ExpenseRequestStatus.APPROVED.value, decided_at=timestamp, decided_by_user_id=actor.id, decision_reason="Approved"))
    if decision.rowcount != 1:
        session.expire(request)
        existing_expense = session.scalar(select(Expense).where(Expense.expense_request_id == request.id))
        if request.status == ExpenseRequestStatus.APPROVED.value and existing_expense:
            return existing_expense, False
        raise ValueError("Expense request already has a terminal decision")
    session.expire(request)
    session.refresh(request)
    session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="APPROVED", actor_user_id=actor.id, message=None, correlation_id=idempotency_key, created_at=timestamp))
    expense = _post_expense(session, request=request, posting_actor=actor, timestamp=timestamp, correlation_id=f"{idempotency_key}:posted")
    requester = session.get(User, request.requester_user_id)
    _enqueue(session, recipient=requester, notification_type="EXPENSE_APPROVED", entity_type="expense_request", entity_id=str(request.id), message=f"✅ {request.request_number} approved and posted by {actor.display_name}.")
    append_audit(session, action="EXPENSE_APPROVED", entity_type="expense_request", entity_id=str(request.id), actor=actor, approver=actor, old_values={"status": "PENDING"}, new_values={"status": "APPROVED", "expense_id": expense.id}, correlation_id=idempotency_key)
    session.add(IdempotencyRecord(namespace="approve_expense", request_key=idempotency_key, response_json={"expense_id": expense.id}))
    session.flush()
    return expense, True


def record_expense_approval_opened(session: Session, *, actor: User, request_id: int, idempotency_key: str) -> tuple[ExpenseRequest, bool]:
    if not actor.is_active or not has_permission(session, actor, "expense.approve"):
        raise PermissionError("User is not authorized to open expense approvals")
    request = session.get(ExpenseRequest, request_id)
    if request is None:
        raise ValueError("Expense request not found")
    if request.requester_user_id == actor.id:
        raise PermissionError("Requester cannot act as approver on their own pending expense")
    existing = session.scalar(select(ExpenseApprovalEvent).where(ExpenseApprovalEvent.event_type == "APPROVER_OPENED", ExpenseApprovalEvent.correlation_id == idempotency_key))
    if existing:
        return request, False
    session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="APPROVER_OPENED", actor_user_id=actor.id, message=None, correlation_id=idempotency_key))
    append_audit(session, action="EXPENSE_APPROVER_OPENED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"status": request.status}, correlation_id=idempotency_key)
    session.flush()
    return request, True


def reject_expense_request(session: Session, *, actor: User, request_id: int, reason: str, idempotency_key: str, occurred_at: datetime | None = None) -> tuple[ExpenseRequest, bool]:
    if not actor.is_active or not has_permission(session, actor, "expense.approve"):
        raise PermissionError("User is not authorized to reject expenses")
    request = session.get(ExpenseRequest, request_id)
    if request is None:
        raise ValueError("Expense request not found")
    if request.requester_user_id == actor.id:
        raise PermissionError("Requester cannot reject their own pending expense")
    if request.status == ExpenseRequestStatus.REJECTED.value:
        return request, False
    if request.status != ExpenseRequestStatus.PENDING.value:
        raise ValueError("Expense request already has a terminal decision")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("A rejection reason is required")
    timestamp = occurred_at or utc_now()
    decision = session.execute(update(ExpenseRequest).where(ExpenseRequest.id == request.id, ExpenseRequest.status == ExpenseRequestStatus.PENDING.value).values(status=ExpenseRequestStatus.REJECTED.value, decided_at=timestamp, decided_by_user_id=actor.id, decision_reason=clean_reason))
    if decision.rowcount != 1:
        session.expire(request)
        if request.status == ExpenseRequestStatus.REJECTED.value:
            return request, False
        raise ValueError("Expense request already has a terminal decision")
    session.expire(request)
    session.refresh(request)
    session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="REJECTED", actor_user_id=actor.id, message=clean_reason, correlation_id=idempotency_key, created_at=timestamp))
    requester = session.get(User, request.requester_user_id)
    _enqueue(session, recipient=requester, notification_type="EXPENSE_REJECTED", entity_type="expense_request", entity_id=str(request.id), message=f"❌ {request.request_number} rejected by {actor.display_name}. Reason: {clean_reason}")
    append_audit(session, action="EXPENSE_REJECTED", entity_type="expense_request", entity_id=str(request.id), actor=actor, approver=actor, old_values={"status": "PENDING"}, new_values={"status": "REJECTED"}, reason=clean_reason, correlation_id=idempotency_key)
    session.add(IdempotencyRecord(namespace="reject_expense", request_key=idempotency_key, response_json={"request_id": request.id}))
    session.flush()
    return request, True


def ask_expense_question(session: Session, *, actor: User, request_id: int, question: str, idempotency_key: str) -> tuple[ExpenseRequest, bool]:
    if not actor.is_active or not has_permission(session, actor, "expense.approve"):
        raise PermissionError("User is not authorized to question expenses")
    request = session.get(ExpenseRequest, request_id)
    if request is None or request.status != ExpenseRequestStatus.PENDING.value:
        raise ValueError("Expense request is not pending")
    if request.requester_user_id == actor.id:
        raise PermissionError("Requester cannot act as approver on their own pending expense")
    clean = question.strip()
    if not clean:
        raise ValueError("Question is required")
    existing = session.scalar(select(ExpenseApprovalEvent).where(ExpenseApprovalEvent.event_type == "QUESTION_ASKED", ExpenseApprovalEvent.correlation_id == idempotency_key))
    if existing:
        return request, False
    session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="QUESTION_ASKED", actor_user_id=actor.id, message=clean, correlation_id=idempotency_key))
    requester = session.get(User, request.requester_user_id)
    _enqueue(session, recipient=requester, notification_type="EXPENSE_QUESTION", entity_type="expense_request", entity_id=str(request.id), message=f"💬 Question about {request.request_number} from {actor.display_name}: {clean}\nReply with /expense_reply {request.id} your response")
    append_audit(session, action="EXPENSE_QUESTION_ASKED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"status": "PENDING"}, reason=clean, correlation_id=idempotency_key)
    session.flush()
    return request, True


def respond_to_expense_question(session: Session, *, actor: User, request_id: int, response: str, idempotency_key: str) -> tuple[ExpenseRequest, bool]:
    request = session.get(ExpenseRequest, request_id)
    if request is None or request.status != ExpenseRequestStatus.PENDING.value:
        raise ValueError("Expense request is not pending")
    if request.requester_user_id != actor.id:
        raise PermissionError("Only the requester may respond")
    clean = response.strip()
    if not clean:
        raise ValueError("Response is required")
    existing = session.scalar(select(ExpenseApprovalEvent).where(ExpenseApprovalEvent.event_type == "REQUESTER_RESPONDED", ExpenseApprovalEvent.correlation_id == idempotency_key))
    if existing:
        return request, False
    session.add(ExpenseApprovalEvent(expense_request_id=request.id, event_type="REQUESTER_RESPONDED", actor_user_id=actor.id, message=clean, correlation_id=idempotency_key))
    for approver in _authorized_approvers(session, actor.id):
        _enqueue(session, recipient=approver, notification_type="EXPENSE_RESPONSE", entity_type="expense_request", entity_id=str(request.id), message=f"💬 Response for {request.request_number} from {actor.display_name}: {clean}")
    append_audit(session, action="EXPENSE_REQUESTER_RESPONDED", entity_type="expense_request", entity_id=str(request.id), actor=actor, new_values={"status": "PENDING"}, reason=clean, correlation_id=idempotency_key)
    session.flush()
    return request, True


def reverse_expense(session: Session, *, actor: User, expense_id: int, reason: str, idempotency_key: str, occurred_at: datetime | None = None) -> tuple[Expense, bool]:
    if not actor.is_active or not has_permission(session, actor, "expense.correct"):
        raise PermissionError("User is not authorized to reverse expenses")
    existing_key = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.namespace == "reverse_expense", IdempotencyRecord.request_key == idempotency_key))
    if existing_key:
        return session.get(Expense, int(existing_key.response_json["expense_id"])), False
    expense = session.get(Expense, expense_id)
    if expense is None:
        raise ValueError("Expense not found")
    if expense.status != ExpenseStatus.POSTED.value:
        raise ValueError("Expense is already reversed")
    clean = reason.strip()
    if not clean:
        raise ValueError("A reversal reason is required")
    timestamp = occurred_at or utc_now()
    original_ledger = session.scalar(select(LedgerEntry).where(LedgerEntry.source_entity_type == "expense", LedgerEntry.source_entity_id == str(expense.id), LedgerEntry.entry_type == "EXPENSE"))
    expense.status = ExpenseStatus.REVERSED.value
    expense.reversed_at = timestamp
    expense.reversed_by_user_id = actor.id
    expense.reversal_reason = clean
    session.add(ExpenseCorrection(original_expense_id=expense.id, reason=clean, actor_user_id=actor.id, created_at=timestamp))
    session.add(LedgerEntry(business_day_id=expense.business_day_id, entry_type="EXPENSE_REVERSAL", direction="INFLOW", amount_minor=expense.amount_minor, currency=expense.currency, payment_method=_payment_method(expense.payment_source), source_entity_type="expense_reversal", source_entity_id=str(expense.id), actor_user_id=actor.id, reverses_ledger_entry_id=original_ledger.id if original_ledger else None, occurred_at=timestamp))
    append_audit(session, action="EXPENSE_REVERSED", entity_type="expense", entity_id=str(expense.id), actor=actor, old_values={"status": "POSTED"}, new_values={"status": "REVERSED"}, reason=clean, correlation_id=idempotency_key)
    session.add(IdempotencyRecord(namespace="reverse_expense", request_key=idempotency_key, response_json={"expense_id": expense.id}))
    session.flush()
    return expense, True


def expense_activity(session: Session, *, requester: User, staff_user_id: int | None = None, limit: int = 20) -> list[ExpenseRequest]:
    target = staff_user_id or requester.id
    if target != requester.id and not (has_permission(session, requester, "expense.view_all") or has_permission(session, requester, "reports.view_all")):
        raise PermissionError("Staff may view only their own expense activity")
    return list(session.scalars(select(ExpenseRequest).options(selectinload(ExpenseRequest.category), selectinload(ExpenseRequest.attachments)).where(ExpenseRequest.requester_user_id == target).order_by(ExpenseRequest.submitted_at.desc()).limit(min(max(limit, 1), 100))))
