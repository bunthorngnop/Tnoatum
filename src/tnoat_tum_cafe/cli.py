from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import subprocess
import sys

from sqlalchemy import text

from .bootstrap import seed_foundation
from .config import load_settings
from .db import create_database_engine, session_factory
from .models import DiscountRule, ExpenseCategory, ExpenseLimit, Role, User, UserRole
from .services.audit import append_audit
from .services.auth import get_user_by_telegram_id, has_permission
from .services.business_days import open_business_day
from .services.catalog import import_catalog
from .services.expenses import reverse_expense
from .services.cash import cash_status, record_cash_count, record_cash_movement, record_retained_float, reverse_cash_movement
from .services.money import parse_money


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
    limit_parser = subparsers.add_parser("set-expense-limit")
    scope = limit_parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--role", choices=("STAFF", "CASHIER", "MANAGER", "OWNER"))
    scope.add_argument("--user-telegram-id", type=int)
    limit_parser.add_argument("--currency", choices=("KHR", "USD"), required=True)
    limit_parser.add_argument("--amount", required=True, help="Whole riel for KHR or decimal USD")
    limit_parser.add_argument("--actor-telegram-id", type=int, required=True)
    receipt_parser = subparsers.add_parser("set-expense-category-receipt")
    receipt_parser.add_argument("--category-code", required=True)
    receipt_parser.add_argument("--required", choices=("true", "false"), required=True)
    receipt_parser.add_argument("--actor-telegram-id", type=int, required=True)
    reverse_parser = subparsers.add_parser("reverse-expense")
    reverse_parser.add_argument("--expense-id", type=int, required=True)
    reverse_parser.add_argument("--reason", required=True)
    reverse_parser.add_argument("--actor-telegram-id", type=int, required=True)
    cash_parser = subparsers.add_parser("record-cash")
    cash_parser.add_argument("--type", choices=("OPENING_FLOAT", "DEPOSIT", "WITHDRAWAL", "OWNER_WITHDRAWAL", "ADJUSTMENT"), required=True)
    cash_parser.add_argument("--direction", choices=("INFLOW", "OUTFLOW"))
    cash_parser.add_argument("--currency", choices=("KHR", "USD"), required=True)
    cash_parser.add_argument("--amount", required=True)
    cash_parser.add_argument("--reason", required=True)
    cash_parser.add_argument("--actor-telegram-id", type=int, required=True)
    cash_status_parser = subparsers.add_parser("cash-status")
    cash_status_parser.add_argument("--actor-telegram-id", type=int, required=True)
    count_parser = subparsers.add_parser("cash-count")
    count_parser.add_argument("--khr", required=True)
    count_parser.add_argument("--usd", required=True)
    count_parser.add_argument("--actor-telegram-id", type=int, required=True)
    retained_parser = subparsers.add_parser("record-retained-float")
    retained_parser.add_argument("--currency", choices=("KHR", "USD"), required=True)
    retained_parser.add_argument("--amount", required=True)
    retained_parser.add_argument("--reason", required=True)
    retained_parser.add_argument("--actor-telegram-id", type=int, required=True)
    reverse_cash_parser = subparsers.add_parser("reverse-cash")
    reverse_cash_parser.add_argument("--movement-id", type=int, required=True)
    reverse_cash_parser.add_argument("--reason", required=True)
    reverse_cash_parser.add_argument("--actor-telegram-id", type=int, required=True)
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
        elif args.command == "set-expense-limit":
            if not has_permission(session, actor, "settings.manage"):
                raise SystemExit("Actor lacks settings.manage permission")
            amount_minor = parse_money(args.amount, args.currency)
            role = session.query(Role).filter_by(code=args.role).one() if args.role else None
            target_user = get_user_by_telegram_id(session, args.user_telegram_id) if args.user_telegram_id else None
            if args.user_telegram_id and target_user is None:
                raise SystemExit("Target user is not active or does not exist")
            query = session.query(ExpenseLimit).filter_by(currency=args.currency)
            query = query.filter_by(role_id=role.id) if role else query.filter_by(user_id=target_user.id)
            limit = query.one_or_none()
            old_amount = limit.amount_minor if limit else None
            if limit is None:
                limit = ExpenseLimit(role_id=role.id if role else None, user_id=target_user.id if target_user else None, currency=args.currency, amount_minor=amount_minor, created_by_user_id=actor.id)
                session.add(limit)
            else:
                limit.amount_minor = amount_minor
                limit.is_active = True
                limit.created_by_user_id = actor.id
            session.flush()
            append_audit(session, action="EXPENSE_LIMIT_SET", entity_type="expense_limit", entity_id=str(limit.id) if limit.id else None, actor=actor, old_values={"amount_minor": old_amount}, new_values={"amount_minor": amount_minor, "currency": args.currency, "role": args.role, "user_telegram_id": args.user_telegram_id})
            print(f"Expense limit set to {args.amount} {args.currency}.")
        elif args.command == "set-expense-category-receipt":
            if not has_permission(session, actor, "settings.manage"):
                raise SystemExit("Actor lacks settings.manage permission")
            category = session.query(ExpenseCategory).filter_by(code=args.category_code.upper()).one_or_none()
            if category is None:
                raise SystemExit("Expense category not found")
            old = category.receipt_required
            category.receipt_required = args.required == "true"
            append_audit(session, action="EXPENSE_CATEGORY_RECEIPT_POLICY_SET", entity_type="expense_category", entity_id=str(category.id), actor=actor, old_values={"receipt_required": old}, new_values={"receipt_required": category.receipt_required})
            print(f"Receipt requirement for {category.code}: {category.receipt_required}.")
        elif args.command == "reverse-expense":
            expense, created = reverse_expense(session, actor=actor, expense_id=args.expense_id, reason=args.reason, idempotency_key=f"cli-reverse-expense:{uuid4()}")
            print(f"Expense {expense.expense_number} {'reversed' if created else 'already reversed'}.")
        elif args.command == "record-cash":
            direction = args.direction or ("INFLOW" if args.type in {"OPENING_FLOAT", "DEPOSIT"} else "OUTFLOW")
            if args.type == "ADJUSTMENT" and args.direction is None:
                raise SystemExit("--direction is required for ADJUSTMENT")
            movement, created = record_cash_movement(session, actor=actor, movement_type=args.type, direction=direction, amount_minor=parse_money(args.amount, args.currency), currency=args.currency, reason=args.reason, idempotency_key=f"cli-cash:{uuid4()}")
            print(f"Cash movement #{movement.id} {'recorded' if created else 'already recorded'}.")
        elif args.command == "cash-status":
            status = cash_status(session, actor=actor)
            print(f"KHR expected={status.expected_khr_minor}; USD expected={status.expected_usd_minor}; ABA KHR={status.aba_khr_minor}; ABA USD={status.aba_usd_minor}")
        elif args.command == "cash-count":
            count, created = record_cash_count(session, actor=actor, actual_khr_minor=parse_money(args.khr, "KHR"), actual_usd_minor=parse_money(args.usd, "USD"), idempotency_key=f"cli-cash-count:{uuid4()}")
            print(f"Cash count #{count.id} {'recorded' if created else 'already recorded'}; KHR difference={count.difference_khr_minor}; USD difference={count.difference_usd_minor}.")
        elif args.command == "record-retained-float":
            retained, created = record_retained_float(session, actor=actor, currency=args.currency, amount_minor=parse_money(args.amount, args.currency), reason=args.reason, idempotency_key=f"cli-retained:{uuid4()}")
            print(f"Retained float #{retained.id} {'recorded' if created else 'already recorded'}; confirmation is still required for a future opening.")
        elif args.command == "reverse-cash":
            movement, created = reverse_cash_movement(session, actor=actor, movement_id=args.movement_id, reason=args.reason, idempotency_key=f"cli-reverse-cash:{uuid4()}")
            print(f"Cash reversal #{movement.id} {'recorded' if created else 'already recorded'}.")


if __name__ == "__main__":
    main()
