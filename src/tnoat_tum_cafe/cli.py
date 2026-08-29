from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys

from sqlalchemy import text

from .bootstrap import seed_foundation
from .config import load_settings
from .db import create_database_engine, session_factory
from .models import DiscountRule, Role, User, UserRole
from .services.audit import append_audit
from .services.auth import get_user_by_telegram_id, has_permission
from .services.business_days import open_business_day
from .services.catalog import import_catalog


def _upgrade() -> None:
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tnoat Tum Cafe Phase 0 administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init-db", "bootstrap", "health", "run-bot"):
        subparsers.add_parser(command)
    catalog = subparsers.add_parser("import-catalog")
    catalog.add_argument("path", type=Path)
    mode = catalog.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--verified", action="store_true")
    catalog.add_argument("--actor-telegram-id", type=int, required=True)
    day = subparsers.add_parser("open-day")
    day.add_argument("--actor-telegram-id", type=int, required=True)
    discount = subparsers.add_parser("add-discount")
    discount.add_argument("percent", type=int)
    discount.add_argument("--requires-approval", action="store_true")
    discount.add_argument("--actor-telegram-id", type=int, required=True)
    user_parser = subparsers.add_parser("add-user")
    user_parser.add_argument("--telegram-id", type=int, required=True)
    user_parser.add_argument("--name", required=True)
    user_parser.add_argument("--role", choices=("STAFF", "CASHIER", "MANAGER", "OWNER"), required=True)
    user_parser.add_argument("--actor-telegram-id", type=int, required=True)
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "init-db":
        _upgrade()
        return
    if args.command == "run-bot":
        if not settings.telegram_bot_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is missing from .env")
        from .telegram_bot import run_bot
        run_bot(settings)
        return
    engine = create_database_engine(settings.database_url)
    if args.command == "health":
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("OK: configuration loaded and database reachable")
        return
    _upgrade()
    with session_factory(engine)() as session, session.begin():
        if args.command == "bootstrap":
            seed_foundation(session, settings)
            print("Foundation roles/settings seeded. Owner users created only for configured numeric IDs.")
            return
        actor = get_user_by_telegram_id(session, args.actor_telegram_id)
        if actor is None:
            raise SystemExit("Configured active actor not found; run bootstrap first")
        if args.command == "import-catalog":
            if not has_permission(session, actor, "catalog.manage"):
                raise SystemExit("Actor lacks catalog.manage permission")
            categories, products = import_catalog(session, args.path, is_demo=args.demo, verified=args.verified, actor=actor)
            print(f"Imported {categories} categories and {products} products.")
        elif args.command == "open-day":
            if not has_permission(session, actor, "cash.open"):
                raise SystemExit("Actor lacks cash.open permission")
            now = datetime.now(settings.timezone)
            day = open_business_day(session, business_date=now.date(), actor=actor, opened_at=now)
            print(f"Opened business day {day.business_date}.")
        elif args.command == "add-discount":
            if not has_permission(session, actor, "settings.manage"):
                raise SystemExit("Actor lacks settings.manage permission")
            if not 0 <= args.percent <= 100:
                raise SystemExit("Discount percent must be from 0 through 100")
            basis_points = args.percent * 100
            if session.query(DiscountRule).filter_by(basis_points=basis_points).first():
                raise SystemExit("That discount already exists")
            session.add(DiscountRule(name=f"{args.percent}%", basis_points=basis_points, requires_approval=args.requires_approval))
            print(f"Added {args.percent}% discount rule.")
        elif args.command == "add-user":
            if not has_permission(session, actor, "users.manage"):
                raise SystemExit("Actor lacks users.manage permission")
            if args.telegram_id <= 0 or not args.name.strip():
                raise SystemExit("Telegram ID must be positive and name is required")
            if session.query(User).filter_by(telegram_user_id=args.telegram_id).first():
                raise SystemExit("Telegram user already exists")
            role = session.query(Role).filter_by(code=args.role).one()
            user = User(telegram_user_id=args.telegram_id, display_name=args.name.strip())
            session.add(user)
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=role.id))
            append_audit(session, action="USER_CREATED", entity_type="user", entity_id=str(user.id), actor=actor, new_values={"telegram_user_id": args.telegram_id, "display_name": user.display_name, "role": role.code})
            print(f"Added {user.display_name} as {role.code}.")


if __name__ == "__main__":
    main()
