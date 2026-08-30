from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from secrets import token_urlsafe
from time import monotonic
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .config import Settings, load_settings
from .db import create_database_engine, session_factory
from .models import AuditLog, BusinessDay, CashCount, ClosingRecord, DiscountRule, Expense, ExpenseLimit, ExpenseRequest, LedgerEntry, Permission, Product, ProductCategory, ProductSuggestedPrice, Role, RolePermission, Sale, SaleItem, User
from .services.audit import append_audit
from .services.auth import get_user_by_telegram_id, has_permission
from .services.money import format_money

def _summary(session:Session,start:date|None=None,end:date|None=None)->dict:
    days=select(BusinessDay.id)
    if start: days=days.where(BusinessDay.business_date>=start)
    if end: days=days.where(BusinessDay.business_date<=end)
    ids=days.scalar_subquery()
    totals={}
    for currency in ("KHR","USD"):
        for method in ("CASH","ABA_KHQR"):
            inflow=session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor),0)).where(LedgerEntry.business_day_id.in_(ids),LedgerEntry.currency==currency,LedgerEntry.payment_method==method,LedgerEntry.direction=="INFLOW")) or 0
            outflow=session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor),0)).where(LedgerEntry.business_day_id.in_(ids),LedgerEntry.currency==currency,LedgerEntry.payment_method==method,LedgerEntry.direction=="OUTFLOW")) or 0
            totals[f"{currency}_{method}"]=int(inflow-outflow)
    return {"ledger":totals,"sales":session.scalar(select(func.count(Sale.id)).where(Sale.business_day_id.in_(ids))) or 0,"expenses":session.scalar(select(func.count(Expense.id)).where(Expense.business_day_id.in_(ids))) or 0,"pending_approvals":session.scalar(select(func.count(ExpenseRequest.id)).where(ExpenseRequest.status=="PENDING")) or 0}

def create_dashboard_app(settings:Settings|None=None)->FastAPI:
    settings=settings or load_settings()
    if settings.dashboard_host not in {"127.0.0.1","localhost","::1"}: raise ValueError("Dashboard binds to localhost only by default")
    if not settings.dashboard_access_token: raise ValueError("DASHBOARD_ACCESS_TOKEN is required")
    factory=session_factory(create_database_engine(settings.database_url)); sessions:dict[str,float]={}
    app=FastAPI(title="Tnoat Tum Cafe Owner Dashboard",docs_url=None,redoc_url=None)
    def auth(request:Request):
        token=request.cookies.get("cafe_dashboard_session")
        if not token or sessions.get(token,0)<monotonic(): raise HTTPException(401,"Dashboard login required")
    def db():
        with factory() as session: yield session
    @app.get("/login",response_class=HTMLResponse)
    def login_page(): return "<h1>☕ Tnoat Tum Cafe</h1><form method='post'><input name='token' type='password' required><button>Owner Login</button></form>"
    @app.post("/login")
    def login(token:str=Form(...)):
        import hmac
        if not hmac.compare_digest(token,settings.dashboard_access_token): raise HTTPException(401,"Invalid dashboard token")
        sid=token_urlsafe(32); sessions[sid]=monotonic()+settings.dashboard_session_minutes*60
        response=RedirectResponse("/",303); response.set_cookie("cafe_dashboard_session",sid,httponly=True,samesite="strict",max_age=settings.dashboard_session_minutes*60); return response
    @app.get("/",response_class=HTMLResponse,dependencies=[Depends(auth)])
    def home(session:Session=Depends(db)):
        today=_summary(session,date.today(),date.today()); l=today["ledger"]
        return f"""<!doctype html><meta name='viewport' content='width=device-width'><style>body{{font:16px system-ui;margin:2rem;background:#fff8ed;color:#38220f}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}}.card{{background:white;padding:1rem;border-radius:14px;box-shadow:0 2px 10px #0002}}a{{color:#8b4513}}</style><h1>☕ Tnoat Tum Cafe — Owner Dashboard</h1><div class='grid'><div class='card'>Sales<br><b>{today['sales']}</b></div><div class='card'>Expenses<br><b>{today['expenses']}</b></div><div class='card'>KHR Cash<br><b>{format_money(l['KHR_CASH'],'KHR')}</b></div><div class='card'>USD Cash<br><b>{format_money(l['USD_CASH'],'USD')}</b></div><div class='card'>ABA KHR<br><b>{format_money(l['KHR_ABA_KHQR'],'KHR')}</b></div><div class='card'>Pending approvals<br><b>{today['pending_approvals']}</b></div></div><p><a href='/api/today'>Today JSON</a> · <a href='/api/reports'>Reports</a> · <a href='/api/catalog'>Catalog</a> · <a href='/api/users'>Users</a> · <a href='/api/closings'>Closings</a> · <a href='/api/audit'>Audit</a></p>"""
    @app.get("/api/today",dependencies=[Depends(auth)])
    def today(session:Session=Depends(db)): return _summary(session,date.today(),date.today())
    @app.get("/api/reports",dependencies=[Depends(auth)])
    def reports(start:date|None=None,end:date|None=None,session:Session=Depends(db)): return _summary(session,start,end)
    @app.get("/api/catalog",dependencies=[Depends(auth)])
    def catalog(session:Session=Depends(db)): return {"categories":[{"id":x.id,"code":x.code,"name":x.name} for x in session.scalars(select(ProductCategory))],"products":[{"id":x.id,"code":x.code,"name":x.name,"mode":x.pricing_mode,"price_minor":x.fixed_price_minor,"currency":x.fixed_price_currency} for x in session.scalars(select(Product))],"suggested_prices":[{"product_id":x.product_id,"amount_minor":x.amount_minor,"currency":x.currency} for x in session.scalars(select(ProductSuggestedPrice))],"discounts":[{"id":x.id,"basis_points":x.basis_points,"requires_approval":x.requires_approval} for x in session.scalars(select(DiscountRule))]}
    @app.get("/api/users",dependencies=[Depends(auth)])
    def users(session:Session=Depends(db)): return {"users":[{"id":x.id,"telegram_id":x.telegram_user_id,"name":x.display_name,"active":x.is_active} for x in session.scalars(select(User))],"roles":[{"id":x.id,"code":x.code} for x in session.scalars(select(Role))],"permissions":[x.code for x in session.scalars(select(Permission))]}
    @app.get("/api/expenses",dependencies=[Depends(auth)])
    def expenses(session:Session=Depends(db)): return {"requests":[{"id":x.id,"amount_minor":x.amount_minor,"currency":x.currency,"status":x.status} for x in session.scalars(select(ExpenseRequest).order_by(ExpenseRequest.id.desc()).limit(100))],"limits":[{"role_id":x.role_id,"user_id":x.user_id,"currency":x.currency,"amount_minor":x.amount_minor} for x in session.scalars(select(ExpenseLimit))]}
    @app.get("/api/closings",dependencies=[Depends(auth)])
    def closings(session:Session=Depends(db)): return [{"id":x.id,"business_day_id":x.business_day_id,"khr_difference":x.difference_khr_minor,"usd_difference":x.difference_usd_minor,"closed_at":x.closed_at} for x in session.scalars(select(ClosingRecord).order_by(ClosingRecord.id.desc()))]
    @app.get("/api/audit",dependencies=[Depends(auth)])
    def audit(session:Session=Depends(db)): return [{"id":x.id,"action":x.action,"entity_type":x.entity_type,"entity_id":x.entity_id,"occurred_at":x.occurred_at} for x in session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200))]
    @app.post("/api/products/{product_id}/price",dependencies=[Depends(auth)])
    def update_price(product_id:int,amount_minor:int,currency:str,actor_telegram_id:int=Header(alias="X-Actor-Telegram-ID"),session:Session=Depends(db)):
        actor=get_user_by_telegram_id(session,actor_telegram_id)
        if not actor or not has_permission(session,actor,"catalog.manage"): raise HTTPException(403,"catalog.manage required")
        product=session.get(Product,product_id)
        if not product or product.pricing_mode!="FIXED_PRICE" or amount_minor<=0 or currency not in {"KHR","USD"}: raise HTTPException(400,"Invalid fixed price update")
        old={"amount_minor":product.fixed_price_minor,"currency":product.fixed_price_currency}; product.fixed_price_minor=amount_minor; product.fixed_price_currency=currency
        append_audit(session,action="PRODUCT_PRICE_UPDATED",entity_type="product",entity_id=str(product.id),actor=actor,old_values=old,new_values={"amount_minor":amount_minor,"currency":currency}); session.commit(); return {"updated":True}
    return app

def run_dashboard(settings:Settings)->None:
    import uvicorn
    uvicorn.run(create_dashboard_app(settings),host=settings.dashboard_host,port=settings.dashboard_port)
