from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Permission, RolePermission, User, UserPermissionOverride, UserRole


def get_user_by_telegram_id(session: Session, telegram_user_id: int) -> User | None:
    if telegram_user_id <= 0:
        return None
    return session.scalar(select(User).where(User.telegram_user_id == telegram_user_id, User.is_active.is_(True)))


def has_permission(session: Session, user: User, permission_code: str) -> bool:
    permission_id = session.scalar(select(Permission.id).where(Permission.code == permission_code))
    if permission_id is None or not user.is_active:
        return False
    override = session.scalar(
        select(UserPermissionOverride.allowed).where(
            UserPermissionOverride.user_id == user.id,
            UserPermissionOverride.permission_id == permission_id,
        )
    )
    if override is not None:
        return override
    return session.scalar(
        select(RolePermission.permission_id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user.id, RolePermission.permission_id == permission_id)
        .limit(1)
    ) is not None

