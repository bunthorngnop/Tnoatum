from datetime import datetime,timezone
from pathlib import Path
import os,sqlite3
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.db import Base
from tnoat_tum_cafe.models import BackupMetadata,User
from tnoat_tum_cafe.services.backup import create_backup,restore_backup,verify_backup

def test_verified_backup_restore_and_no_overwrite(tmp_path):
    live=tmp_path/"test-live.sqlite3"; backups=tmp_path/"backups"; engine=create_engine(f"sqlite:///{live.as_posix()}"); Base.metadata.create_all(engine)
    settings=Settings("Cafe","Asia/Phnom_Penh",__import__('datetime').time(8),__import__('datetime').time(17),__import__('datetime').time(18),f"sqlite:///{live.as_posix()}",(123456789,),("KHR","USD"),backups,30)
    with Session(engine) as session,session.begin(): seed_foundation(session,settings)
    with Session(engine) as session,session.begin():
        owner=session.query(User).filter_by(telegram_user_id=123456789).one(); row=create_backup(session,actor=owner,database_url=settings.database_url,backup_directory=backups,retention_days=30,now=datetime(2026,8,30,tzinfo=timezone.utc)); path=Path(row.relative_path)
    assert verify_backup(path)["integrity_ok"]
    restored=tmp_path/"restored.sqlite3"; assert restore_backup(backup_path=path,target_path=restored)["integrity_ok"]
    with sqlite3.connect(restored) as db: assert db.execute("select count(*) from users").fetchone()[0]==1
    with pytest.raises(ValueError,match="refusing"): restore_backup(backup_path=path,target_path=restored)

def test_corrupt_backup_rejected(tmp_path):
    bad=tmp_path/"bad.sqlite3"; bad.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError): verify_backup(bad)

def test_retention_removes_only_old_generations(tmp_path):
    live=tmp_path/"live.sqlite3"; backups=tmp_path/"backups"; backups.mkdir(); sqlite3.connect(live).execute("create table x(a)").connection.commit()
    old=backups/"tnoat_tum_cafe_20000101_000000_000000.sqlite3"; old.write_bytes(b"old"); os.utime(old,(1,1))
    engine=create_engine(f"sqlite:///{live.as_posix()}"); Base.metadata.create_all(engine)
    with Session(engine) as session,session.begin():
        row=create_backup(session,actor=None,database_url=f"sqlite:///{live.as_posix()}",backup_directory=backups,retention_days=1); created_path=Path(row.relative_path)
    assert created_path.exists() and not old.exists()
