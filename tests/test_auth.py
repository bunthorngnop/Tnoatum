from datetime import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import Permission, UserPermissionOverride
from tnoat_tum_cafe.services.auth import get_user_by_telegram_id, has_permission


def _settings(owner_id: int) -> Settings:
    return Settings("Tnoat Tum Cafe", "Asia/Phnom_Penh", time(8), time(17), time(18), "sqlite:///:memory:", (owner_id,), ("KHR", "USD"), Path("backups"), 30)


def test_numeric_telegram_identity_and_configurable_permissions(session: Session) -> None:
    seed_foundation(session, _settings(987654321))
    session.commit()
    user = get_user_by_telegram_id(session, 987654321)
    assert user is not None
    assert has_permission(session, user, "users.manage") is True
    permission = session.scalar(select(Permission).where(Permission.code == "users.manage"))
    session.add(UserPermissionOverride(user_id=user.id, permission_id=permission.id, allowed=False, reason="test override"))
    session.commit()
    assert has_permission(session, user, "users.manage") is False


def test_unknown_telegram_identity_is_not_authorized(session: Session) -> None:
    assert get_user_by_telegram_id(session, 999) is None

