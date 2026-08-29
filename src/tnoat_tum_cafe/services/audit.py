from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def append_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    actor: User | None = None,
    entity_id: str | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    reason: str | None = None,
    approver: User | None = None,
    correlation_id: str | None = None,
) -> AuditLog:
    record = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_telegram_user_id=actor.telegram_user_id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        approver_user_id=approver.id if approver else None,
        correlation_id=correlation_id or str(uuid4()),
    )
    session.add(record)
    return record

