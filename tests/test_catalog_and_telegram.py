from pathlib import Path
from datetime import time
import warnings

import pytest
from sqlalchemy.orm import Session

from tnoat_tum_cafe.config import Settings
from tnoat_tum_cafe.models import Product
from tnoat_tum_cafe.services.catalog import import_catalog
from tnoat_tum_cafe.services.money import parse_money
from tnoat_tum_cafe.telegram_bot import build_application
from telegram.warnings import PTBUserWarning


def test_demo_catalog_is_explicit_and_separate(session: Session) -> None:
    categories, products = import_catalog(session, Path("config/demo_catalog.json"), is_demo=True, verified=False)
    session.commit()
    assert (categories, products) == (2, 2)
    assert all(product.is_demo for product in session.query(Product).all())


def test_production_catalog_requires_verified_flag(session: Session) -> None:
    with pytest.raises(ValueError, match="verified=True"):
        import_catalog(session, Path("config/demo_catalog.json"), is_demo=False, verified=False)


def test_exact_money_input_rejects_fractional_riel() -> None:
    assert parse_money("2.50", "USD") == 250
    assert parse_money("4,000", "KHR") == 4000
    with pytest.raises(ValueError, match="whole riel"):
        parse_money("4000.50", "KHR")


def test_telegram_application_builds_without_network() -> None:
    configured = Settings("Tnoat Tum Cafe", "Asia/Phnom_Penh", time(8), time(17), time(18), "sqlite:///:memory:", (), ("KHR", "USD"), Path("backups"), 30, "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PTBUserWarning)
        application = build_application(configured)
    assert application.bot.token.startswith("123456:")
