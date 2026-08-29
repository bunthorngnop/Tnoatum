import pytest
from sqlalchemy.orm import Session

from tnoat_tum_cafe.models import User
from tnoat_tum_cafe.services.audit import append_audit


def test_audit_records_are_append_only(session: Session, owner: User) -> None:
    record = append_audit(session, action="TEST", entity_type="test", actor=owner)
    session.commit()
    record.reason = "attempted edit"
    with pytest.raises(ValueError, match="append-only"):
        session.commit()

