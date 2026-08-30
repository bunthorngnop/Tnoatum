from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import BackupMetadata,User
from .audit import append_audit
from .auth import has_permission

def sqlite_path(database_url:str)->Path:
    prefix="sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"): raise ValueError("Backup supports file-based SQLite databases only")
    return Path(database_url[len(prefix):]).resolve()
def verify_backup(path:Path)->dict:
    path=path.resolve()
    if not path.is_file(): raise ValueError("Backup file not found")
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True) as db: result=db.execute("PRAGMA integrity_check").fetchone()[0]
    digest=sha256(path.read_bytes()).hexdigest()
    return {"path":str(path),"size_bytes":path.stat().st_size,"sha256":digest,"integrity_ok":result=="ok"}
def create_backup(session:Session,*,actor:User|None,database_url:str,backup_directory:Path,retention_days:int,now:datetime|None=None)->BackupMetadata:
    if actor and not has_permission(session,actor,"backup.manage"): raise PermissionError("User lacks backup.manage permission")
    source=sqlite_path(database_url)
    if not source.is_file(): raise ValueError("Runtime database file not found")
    timestamp=now or datetime.now(timezone.utc); directory=backup_directory.resolve(); directory.mkdir(parents=True,exist_ok=True)
    target=directory/f"tnoat_tum_cafe_{timestamp:%Y%m%d_%H%M%S_%f}.sqlite3"
    with sqlite3.connect(source) as src,sqlite3.connect(target) as dst: src.backup(dst)
    result=verify_backup(target)
    if not result["integrity_ok"]: target.unlink(missing_ok=True); raise ValueError("Backup integrity verification failed")
    row=BackupMetadata(relative_path=str(target),size_bytes=result["size_bytes"],sha256=result["sha256"],integrity_ok=True,created_by_user_id=actor.id if actor else None,created_at=timestamp)
    session.add(row); session.flush(); append_audit(session,action="DATABASE_BACKUP_CREATED",entity_type="backup",entity_id=str(row.id),actor=actor,new_values={"size_bytes":row.size_bytes,"sha256":row.sha256,"integrity_ok":True})
    cutoff=timestamp.timestamp()-retention_days*86400
    for old in directory.glob("tnoat_tum_cafe_*.sqlite3"):
        if old!=target and old.stat().st_mtime<cutoff: old.unlink()
    return row
def ensure_daily_backup(session:Session,*,database_url:str,backup_directory:Path,retention_days:int)->BackupMetadata|None:
    today=datetime.now(timezone.utc).date(); latest=session.scalar(select(BackupMetadata).order_by(BackupMetadata.created_at.desc()).limit(1))
    if latest and latest.created_at.date()==today and Path(latest.relative_path).is_file(): return None
    return create_backup(session,actor=None,database_url=database_url,backup_directory=backup_directory,retention_days=retention_days)
def restore_backup(*,backup_path:Path,target_path:Path)->dict:
    source=backup_path.resolve(); target=target_path.resolve(); verify_backup(source)
    if target.exists(): raise ValueError("Restore target already exists; refusing to overwrite data")
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with sqlite3.connect(f"file:{source.as_posix()}?mode=ro",uri=True) as src,sqlite3.connect(target) as dst: src.backup(dst)
        restored=verify_backup(target)
        if not restored["integrity_ok"]: raise ValueError("Restored database integrity check failed")
        return restored
    except Exception:
        target.unlink(missing_ok=True); raise
