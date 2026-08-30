from datetime import date,datetime,time,timezone
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.dashboard import create_dashboard_app
from tnoat_tum_cafe.db import Base
from tnoat_tum_cafe.models import ClosingRecord,DiscountRule,ExpenseCategory,ExpenseLimit,NotificationOutbox,Product,ProductCategory,Role,Sale,User,UserRole
from tnoat_tum_cafe.services.auth import get_user_by_telegram_id
from tnoat_tum_cafe.services.backup import create_backup,restore_backup
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.cash import cash_status,record_cash_count,record_cash_movement
from tnoat_tum_cafe.services.closing import begin_closing,finalize_closing
from tnoat_tum_cafe.services.expenses import AttachmentInput,approve_expense_request,submit_expense_request
from tnoat_tum_cafe.services.sales import CartItemInput,PaymentInput,post_sale

def test_complete_version1_operational_lifecycle(tmp_path):
    live=tmp_path/"lifecycle.sqlite3"; settings=Settings("Tnoat Tum Cafe","Asia/Phnom_Penh",time(8),time(17),time(18),f"sqlite:///{live.as_posix()}",(166792174,),("KHR","USD"),tmp_path/"backups",30,dashboard_access_token="test-dashboard-token")
    engine=create_engine(settings.database_url); Base.metadata.create_all(engine)
    with Session(engine) as s,s.begin():
        seed_foundation(s,settings); owner=get_user_by_telegram_id(s,166792174); staff_role=s.scalar(select(Role).where(Role.code=="STAFF")); staff=User(telegram_user_id=700777,display_name="Lifecycle Staff");s.add(staff);s.flush();s.add(UserRole(user_id=staff.id,role_id=staff_role.id));cat=ProductCategory(code="LIFE",name="Lifecycle");s.add(cat);s.flush();fixed=Product(category_id=cat.id,code="LIFE_FIXED",name="Coffee",pricing_mode="FIXED_PRICE",fixed_price_minor=4000,fixed_price_currency="KHR");opened=Product(category_id=cat.id,code="LIFE_OPEN",name="Food",pricing_mode="OPEN_PRICE");s.add_all([fixed,opened,DiscountRule(name="Lifecycle 10%",basis_points=1000)]);expense_cat=s.scalar(select(ExpenseCategory).where(ExpenseCategory.code=="INGREDIENTS"));s.add(ExpenseLimit(role_id=staff_role.id,currency="KHR",amount_minor=1000,created_by_user_id=owner.id));open_business_day(s,business_date=date(2026,8,30),actor=owner,opened_at=datetime(2026,8,30,1,tzinfo=timezone.utc));record_cash_movement(s,actor=owner,movement_type="OPENING_FLOAT",direction="INFLOW",amount_minor=100000,currency="KHR",reason="Lifecycle opening",idempotency_key="life-open")
    with Session(engine) as s,s.begin():
        owner=get_user_by_telegram_id(s,166792174);staff=get_user_by_telegram_id(s,700777);fixed=s.scalar(select(Product).where(Product.code=="LIFE_FIXED"));opened=s.scalar(select(Product).where(Product.code=="LIFE_OPEN"));expense_cat=s.scalar(select(ExpenseCategory).where(ExpenseCategory.code=="INGREDIENTS"));assert staff
        post_sale(s,actor=staff,items=[CartItemInput(product_id=fixed.id,quantity=1)],discount_basis_points=0,payments=[PaymentInput("CASH","KHR",4000)],idempotency_key="life-fixed")
        post_sale(s,actor=staff,items=[CartItemInput(product_id=opened.id,quantity=1,unit_price_minor=6000,manual_currency="KHR")],discount_basis_points=0,payments=[PaymentInput("ABA_KHQR","KHR",6000)],idempotency_key="life-open-price")
        post_sale(s,actor=staff,items=[CartItemInput(quantity=1,unit_price_minor=200,manual_name="Custom",manual_currency="USD")],discount_basis_points=0,payments=[PaymentInput("CASH","USD",200)],idempotency_key="life-manual")
        post_sale(s,actor=staff,items=[CartItemInput(product_id=fixed.id,quantity=2),CartItemInput(product_id=opened.id,quantity=1,unit_price_minor=2000,manual_currency="KHR")],discount_basis_points=1000,payments=[PaymentInput("CASH","KHR",9000)],idempotency_key="life-cart-discount")
        request=submit_expense_request(s,actor=staff,category_id=expense_cat.id,amount_minor=2000,currency="KHR",payment_source="KHR_CASH",reason="Lifecycle ingredients",attachments=[AttachmentInput("file","unique","PHOTO","image/jpeg",10,"receipts/test.jpg")],idempotency_key="life-expense",within_limit_posts_immediately=False,require_receipt_for_all=True).request;request_id=request.id
    with Session(engine) as s,s.begin():
        owner=get_user_by_telegram_id(s,166792174);approve_expense_request(s,actor=owner,request_id=request_id,idempotency_key="life-approve");record_cash_movement(s,actor=owner,movement_type="DEPOSIT",direction="INFLOW",amount_minor=5000,currency="KHR",reason="Lifecycle deposit",idempotency_key="life-deposit");record_cash_movement(s,actor=owner,movement_type="OWNER_WITHDRAWAL",direction="OUTFLOW",amount_minor=10000,currency="KHR",reason="Lifecycle owner withdrawal",idempotency_key="life-withdraw");status=cash_status(s,actor=owner);count,_=record_cash_count(s,actor=owner,actual_khr_minor=status.expected_khr_minor,actual_usd_minor=status.expected_usd_minor,idempotency_key="life-count");begin_closing(s,actor=owner,idempotency_key="life-closing");closing,_=finalize_closing(s,actor=owner,cash_count_id=count.id,aba_confirmed=True,explanation_khr=None,explanation_usd=None,tolerance_khr_minor=0,tolerance_usd_minor=0,idempotency_key="life-final")
    client=TestClient(create_dashboard_app(settings));login=client.post("/login",data={"token":"test-dashboard-token"},follow_redirects=False);client.cookies.update(login.cookies);report=client.get("/api/reports").json();assert report["sales"]==4 and report["ledger"]["KHR_ABA_KHQR"]==6000
    with Session(engine) as s,s.begin(): owner=get_user_by_telegram_id(s,166792174);backup=create_backup(s,actor=owner,database_url=settings.database_url,backup_directory=settings.backup_directory,retention_days=30);backup_path=Path(backup.relative_path)
    restored=tmp_path/"restored.sqlite3";restore_backup(backup_path=backup_path,target_path=restored);restored_engine=create_engine(f"sqlite:///{restored.as_posix()}")
    with Session(restored_engine) as s:
        assert s.query(Sale).count()==4 and s.query(ClosingRecord).count()==1 and s.scalar(select(NotificationOutbox).where(NotificationOutbox.notification_type=="BUSINESS_DAY_CLOSED"))
