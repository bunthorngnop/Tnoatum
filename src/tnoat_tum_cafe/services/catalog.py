from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Currency, PricingMode, Product, ProductCategory, ProductSuggestedPrice, utc_now
from .audit import append_audit


def active_categories(session: Session) -> list[ProductCategory]:
    return list(session.scalars(select(ProductCategory).where(ProductCategory.is_active.is_(True)).order_by(ProductCategory.sort_order, ProductCategory.name)))


def active_products(session: Session, category_id: int) -> list[Product]:
    return list(session.scalars(select(Product).where(Product.category_id == category_id, Product.is_active.is_(True)).order_by(Product.name)))


def suggested_prices(session: Session, product_id: int) -> list[ProductSuggestedPrice]:
    return list(session.scalars(select(ProductSuggestedPrice).where(ProductSuggestedPrice.product_id == product_id, ProductSuggestedPrice.is_active.is_(True)).order_by(ProductSuggestedPrice.sort_order, ProductSuggestedPrice.amount_minor)))


def import_catalog(session: Session, path: Path, *, is_demo: bool, verified: bool, actor=None) -> tuple[int, int]:
    if not is_demo and not verified:
        raise ValueError("Production catalog imports require explicit verified=True")
    payload = json.loads(path.read_text(encoding="utf-8"))
    categories_created = products_created = 0
    for category_data in payload.get("categories", []):
        category = session.scalar(select(ProductCategory).where(ProductCategory.code == category_data["code"]))
        if category is None:
            category = ProductCategory(code=category_data["code"], name=category_data["name"], icon=category_data.get("icon"), sort_order=int(category_data.get("sort_order", 0)), is_demo=is_demo)
            session.add(category)
            session.flush()
            categories_created += 1
        for product_data in category_data.get("products", []):
            if session.scalar(select(Product.id).where(Product.code == product_data["code"])) is not None:
                raise ValueError(f"Product code already exists: {product_data['code']}")
            mode = PricingMode(product_data["pricing_mode"])
            fixed = product_data.get("fixed_price_minor")
            currency = product_data.get("currency")
            if mode == PricingMode.FIXED_PRICE:
                if not isinstance(fixed, int) or fixed <= 0 or currency not in {item.value for item in Currency}:
                    raise ValueError(f"Fixed product {product_data['code']} requires positive integer fixed_price_minor and KHR/USD currency")
            elif fixed is not None or currency is not None:
                raise ValueError(f"Open-price product {product_data['code']} must not define a fixed price")
            product = Product(category_id=category.id, code=product_data["code"], name=product_data["name"], pricing_mode=mode.value, fixed_price_minor=fixed, fixed_price_currency=currency, is_demo=is_demo, created_at=utc_now(), updated_at=utc_now())
            session.add(product)
            session.flush()
            products_created += 1
            for position, suggestion in enumerate(product_data.get("suggested_prices", [])):
                amount = suggestion["amount_minor"]
                suggestion_currency = suggestion["currency"]
                if not isinstance(amount, int) or amount <= 0 or suggestion_currency not in {item.value for item in Currency}:
                    raise ValueError(f"Invalid suggested price for {product.code}")
                session.add(ProductSuggestedPrice(product_id=product.id, amount_minor=amount, currency=suggestion_currency, sort_order=position))
    append_audit(session, action="CATALOG_IMPORTED", entity_type="catalog", actor=actor, new_values={"path": path.name, "is_demo": is_demo, "verified": verified, "categories_created": categories_created, "products_created": products_created})
    return categories_created, products_created

