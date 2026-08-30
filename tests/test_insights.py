from datetime import date,datetime,time,timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from tnoat_tum_cafe.bootstrap import seed_foundation
from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import Product,ProductAlias,ProductCategory,SmartSuggestion,User
from tnoat_tum_cafe.services.business_days import open_business_day
from tnoat_tum_cafe.services.insights import common_open_prices,decide_suggestion,fuzzy_products,owner_insights,product_convenience,refresh_manual_item_suggestions,toggle_favorite
from tnoat_tum_cafe.services.sales import CartItemInput,PaymentInput,post_sale

def _setup(session:Session,owner:User):
    seed_foundation(session,Settings("Cafe","Asia/Phnom_Penh",time(8),time(17),time(18),"sqlite:///:memory:",(owner.telegram_user_id,),("KHR","USD"),Path("backups"),30)); cat=ProductCategory(code="SMART",name="Smart"); session.add(cat);session.flush(); product=Product(category_id=cat.id,code="OPEN_SMART",name="Lemon Tea",pricing_mode="OPEN_PRICE");session.add(product);session.flush();open_business_day(session,business_date=date(2026,8,30),actor=owner,opened_at=datetime.now(timezone.utc));session.commit();return product

def test_recent_frequent_common_prices_and_fuzzy_alias(session,owner):
    product=_setup(session,owner); session.add(ProductAlias(product_id=product.id,alias="lemontee",created_by_user_id=owner.id));session.commit()
    for i,price in enumerate((4000,4000,5000)):
        post_sale(session,actor=owner,items=[CartItemInput(product_id=product.id,quantity=1,unit_price_minor=price,manual_currency="KHR")],discount_basis_points=0,payments=[PaymentInput("CASH","KHR",price)],idempotency_key=f"smart-{i}");session.commit()
    data=product_convenience(session,user=owner); prices=common_open_prices(session,product.id)
    assert data["recent"][0].id==product.id and data["frequent"][0]["quantity"]==3
    assert prices[0]=={"currency":"KHR","amount_minor":4000,"uses":2} and fuzzy_products(session,"lemont",1)[0].id==product.id
    assert toggle_favorite(session,user=owner,product_id=product.id) is True
    session.commit(); assert product_convenience(session,user=owner)["favorites"][0].id==product.id

def test_manual_suggestion_is_advisory_and_requires_owner_decision(session,owner):
    _setup(session,owner)
    for i in range(3): post_sale(session,actor=owner,items=[CartItemInput(quantity=1,unit_price_minor=6000,manual_name="Special Soup",manual_currency="KHR")],discount_basis_points=0,payments=[PaymentInput("CASH","KHR",6000)],idempotency_key=f"manual-{i}");session.commit()
    rows=refresh_manual_item_suggestions(session);session.commit(); assert len(rows)==1 and rows[0].payload_json["advisory_only"] is True
    suggestion=session.scalar(select(SmartSuggestion)); decide_suggestion(session,actor=owner,suggestion_id=suggestion.id,decision="IGNORED");session.commit()
    assert suggestion.status=="IGNORED" and session.query(Product).count()==1

def test_owner_insights_keep_currencies_uncombined(session,owner):
    _setup(session,owner); result=owner_insights(session,actor=owner)
    assert set(result)=={"busiest_hours","unusual_discounts","unusual_expenses","correction_count","staff_activity","pending_suggestions"}
