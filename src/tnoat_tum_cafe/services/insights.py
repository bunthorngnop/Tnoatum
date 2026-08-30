from __future__ import annotations
from collections import Counter
from difflib import get_close_matches
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from ..models import Expense,Product,ProductAlias,ProductFavorite,Sale,SaleCorrection,SaleItem,SmartSuggestion,User,utc_now
from .audit import append_audit
from .auth import has_permission

def product_convenience(session:Session,*,user:User,limit:int=8)->dict:
    recent=list(session.scalars(select(Product).join(SaleItem,SaleItem.product_id==Product.id).join(Sale,Sale.id==SaleItem.sale_id).where(Sale.staff_user_id==user.id,Product.is_active.is_(True)).order_by(Sale.posted_at.desc()).limit(limit)))
    frequent=list(session.execute(select(Product,func.sum(SaleItem.quantity).label("qty")).join(SaleItem,SaleItem.product_id==Product.id).join(Sale,Sale.id==SaleItem.sale_id).where(Sale.staff_user_id==user.id,Product.is_active.is_(True)).group_by(Product.id).order_by(func.sum(SaleItem.quantity).desc()).limit(limit)).all())
    favorites=list(session.scalars(select(Product).join(ProductFavorite,ProductFavorite.product_id==Product.id).where(ProductFavorite.user_id==user.id,Product.is_active.is_(True))))
    return {"recent":recent,"frequent":[{"product":p,"quantity":int(q)} for p,q in frequent],"favorites":favorites}
def toggle_favorite(session:Session,*,user:User,product_id:int)->bool:
    product=session.get(Product,product_id)
    if not product or not product.is_active: raise ValueError("Product unavailable")
    row=session.get(ProductFavorite,(user.id,product_id))
    if row: session.delete(row); return False
    session.add(ProductFavorite(user_id=user.id,product_id=product_id)); return True
def common_open_prices(session:Session,product_id:int,limit:int=5)->list[dict]:
    rows=session.execute(select(SaleItem.currency,SaleItem.unit_price_minor,func.count(SaleItem.id)).where(SaleItem.product_id==product_id,SaleItem.pricing_mode_snapshot=="OPEN_PRICE").group_by(SaleItem.currency,SaleItem.unit_price_minor).order_by(func.count(SaleItem.id).desc()).limit(limit)).all()
    return [{"currency":c,"amount_minor":a,"uses":n} for c,a,n in rows]
def fuzzy_products(session:Session,query:str,limit:int=5)->list[Product]:
    products=list(session.scalars(select(Product).where(Product.is_active.is_(True)))); aliases=list(session.execute(select(ProductAlias.alias,Product).join(Product,Product.id==ProductAlias.product_id).where(ProductAlias.is_active.is_(True))).all())
    mapping={p.name.casefold():p for p in products}; mapping.update({a.casefold():p for a,p in aliases}); matches=get_close_matches(query.casefold(),list(mapping),n=limit,cutoff=.6); return [mapping[x] for x in matches]
def refresh_manual_item_suggestions(session:Session,*,minimum_uses:int=3)->list[SmartSuggestion]:
    rows=session.execute(select(func.lower(SaleItem.name_snapshot),SaleItem.currency,func.count(SaleItem.id),func.min(SaleItem.unit_price_minor),func.max(SaleItem.unit_price_minor)).where(SaleItem.pricing_mode_snapshot=="MANUAL_ITEM").group_by(func.lower(SaleItem.name_snapshot),SaleItem.currency).having(func.count(SaleItem.id)>=minimum_uses)).all(); created=[]
    for name,currency,uses,low,high in rows:
        key=f"manual:{name}:{currency}"
        if not session.scalar(select(SmartSuggestion).where(SmartSuggestion.key==key)):
            row=SmartSuggestion(suggestion_type="ADD_TO_QUICK_MENU",key=key,payload_json={"name":name,"currency":currency,"uses":uses,"observed_min":low,"observed_max":high,"advisory_only":True}); session.add(row); created.append(row)
    return created
def owner_insights(session:Session,*,actor:User)->dict:
    if not (has_permission(session,actor,"reports.view_all") and has_permission(session,actor,"audit.view")): raise PermissionError("Owner reporting permissions required")
    busiest=[{"hour":h,"sales":n} for h,n in session.execute(select(func.strftime('%H',Sale.posted_at),func.count(Sale.id)).group_by(func.strftime('%H',Sale.posted_at)).order_by(func.count(Sale.id).desc()).limit(5))]
    unusual_discounts=[{"sale_id":x.id,"basis_points":x.discount_basis_points} for x in session.scalars(select(Sale).where(Sale.discount_basis_points>=2000).order_by(Sale.id.desc()).limit(20))]
    unusual_expenses=[{"expense_id":x.id,"amount_minor":x.amount_minor,"currency":x.currency} for x in session.scalars(select(Expense).order_by(Expense.amount_minor.desc()).limit(10))]
    staff=[{"user_id":uid,"sales":n} for uid,n in session.execute(select(Sale.staff_user_id,func.count(Sale.id)).group_by(Sale.staff_user_id).order_by(func.count(Sale.id).desc()))]
    return {"busiest_hours":busiest,"unusual_discounts":unusual_discounts,"unusual_expenses":unusual_expenses,"correction_count":session.scalar(select(func.count(SaleCorrection.id))) or 0,"staff_activity":staff,"pending_suggestions":[{"id":x.id,"type":x.suggestion_type,"payload":x.payload_json} for x in session.scalars(select(SmartSuggestion).where(SmartSuggestion.status=="PENDING"))]}
def decide_suggestion(session:Session,*,actor:User,suggestion_id:int,decision:str)->SmartSuggestion:
    if not has_permission(session,actor,"catalog.manage"): raise PermissionError("catalog.manage required")
    row=session.get(SmartSuggestion,suggestion_id)
    if not row or row.status!="PENDING": raise ValueError("Suggestion is unavailable")
    if decision not in {"ACCEPTED","IGNORED"}: raise ValueError("Invalid decision")
    row.status=decision; row.decided_at=utc_now(); row.decided_by_user_id=actor.id
    append_audit(session,action=f"SMART_SUGGESTION_{decision}",entity_type="smart_suggestion",entity_id=str(row.id),actor=actor,new_values={"status":decision,"advisory_only":True})
    return row
