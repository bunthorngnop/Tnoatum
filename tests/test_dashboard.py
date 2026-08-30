from datetime import time
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.dashboard import create_dashboard_app
from tnoat_tum_cafe.db import Base

def test_dashboard_requires_token_and_separates_money(tmp_path):
    db=tmp_path/"dashboard.sqlite3"; settings=Settings("Tnoat Tum Cafe","Asia/Phnom_Penh",time(8),time(17),time(18),f"sqlite:///{db.as_posix()}",(166792174,),("KHR","USD"),Path("backups"),30,dashboard_access_token="local-secret")
    engine=create_engine(settings.database_url); Base.metadata.create_all(engine)
    with Session(engine) as session,session.begin(): seed_foundation(session,settings)
    client=TestClient(create_dashboard_app(settings))
    assert client.get("/").status_code==401
    assert client.post("/login",data={"token":"wrong"}).status_code==401
    response=client.post("/login",data={"token":"local-secret"},follow_redirects=False)
    assert response.status_code==303
    client.cookies.update(response.cookies)
    report=client.get("/api/reports").json()
    assert set(report["ledger"])=={"KHR_CASH","KHR_ABA_KHQR","USD_CASH","USD_ABA_KHQR"}
    assert client.get("/api/users").status_code==200 and client.get("/api/audit").status_code==200

def test_dashboard_refuses_public_bind():
    settings=Settings("Tnoat Tum Cafe","Asia/Phnom_Penh",time(8),time(17),time(18),"sqlite:///:memory:",(),("KHR","USD"),Path("backups"),30,dashboard_host="0.0.0.0",dashboard_access_token="x")
    try: create_dashboard_app(settings)
    except ValueError as exc: assert "localhost" in str(exc)
    else: raise AssertionError("public bind must be rejected")
