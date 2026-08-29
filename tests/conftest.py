from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from tnoat_tum_cafe.db import Base
from tnoat_tum_cafe.models import Role, User, UserRole


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda dbapi, _record: dbapi.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def owner(session: Session) -> User:
    role = Role(code="OWNER", name="Owner", description="Test owner")
    user = User(telegram_user_id=123456789, display_name="Test Owner", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    session.add_all([role, user])
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.commit()
    return user

