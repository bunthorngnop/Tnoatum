from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import AppSetting, DiscountRule, ExpenseCategory, Permission, Role, RolePermission, User, UserRole
from .services.audit import append_audit


PERMISSIONS = {
    "sale.create": "Create sales (implemented in Phase 1)",
    "sale.correct": "Reverse or replace permitted sales without deleting history",
    "sale.discount.custom": "Apply a custom sale discount without separate approval",
    "catalog.manage": "Manage verified product categories, products, and prices",
    "expense.create": "Create permitted expenses (Phase 2)",
    "expense.approve": "Approve expense requests (Phase 2)",
    "expense.correct": "Reverse a posted expense while preserving history",
    "expense.view_all": "View all staff expense requests and posted expenses",
    "cash.open": "Record opening cash (Phase 3)",
    "cash.view": "View physical cash status and history",
    "cash.deposit": "Record an explicit cash deposit",
    "cash.withdraw": "Record an authorized non-owner withdrawal",
    "cash.owner_withdraw": "Record owner withdrawals and retained-float decisions",
    "cash.adjust": "Record or reverse an authorized cash adjustment",
    "cash.count": "Record actual KHR and USD physical cash counts",
    "business_day.close": "Perform business-day closing (Phase 4)",
    "business_day.reopen": "Reopen a closed business day with audit",
    "users.manage": "Manage users, roles, and permission overrides",
    "settings.manage": "Manage shop and financial settings",
    "audit.view": "View complete audit history",
    "reports.view_all": "View all shop reports",
    "backup.manage": "Manage financial database backups",
}

ROLE_PERMISSIONS = {
    "STAFF": {"sale.create", "sale.correct", "expense.create"},
    "CASHIER": {"sale.create", "sale.correct", "expense.create", "cash.open", "business_day.close"},
    "MANAGER": {"sale.create", "sale.correct", "expense.create", "cash.open", "business_day.close", "reports.view_all"},
    "OWNER": set(PERMISSIONS),
}


def seed_foundation(session: Session, settings: Settings) -> None:
    permissions: dict[str, Permission] = {}
    for code, description in PERMISSIONS.items():
        permission = session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=description)
            session.add(permission)
            session.flush()
        permissions[code] = permission

    roles: dict[str, Role] = {}
    for code in ROLE_PERMISSIONS:
        role = session.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=code.title(), description=f"System {code.lower()} role")
            session.add(role)
            session.flush()
        roles[code] = role
        for permission_code in ROLE_PERMISSIONS[code]:
            if session.get(RolePermission, (role.id, permissions[permission_code].id)) is None:
                session.add(RolePermission(role_id=role.id, permission_id=permissions[permission_code].id))

    setting_values = {
        "shop": {"name": settings.shop_name, "timezone": settings.timezone_name},
        "official_hours": {"open": settings.official_open_time.isoformat(timespec="minutes"), "close": settings.official_close_time.isoformat(timespec="minutes"), "late_reminder": settings.late_reminder_time.isoformat(timespec="minutes")},
        "currencies": {"supported": list(settings.supported_currencies), "conversion_policy": None},
    }
    for key, value in setting_values.items():
        if session.get(AppSetting, key) is None:
            session.add(AppSetting(key=key, value_json=value))

    if session.scalar(select(DiscountRule).where(DiscountRule.basis_points == 0)) is None:
        session.add(DiscountRule(name="No discount", basis_points=0, requires_approval=False))

    default_expense_categories = (
        ("INGREDIENTS", "Ingredients", "🥬"), ("ICE", "Ice", "🧊"),
        ("MILK", "Milk", "🥛"), ("FOOD_SUPPLIES", "Food Supplies", "🍚"),
        ("DELIVERY", "Delivery", "🛵"), ("REPAIR", "Repair", "🔧"),
        ("UTILITIES", "Utilities", "💡"), ("OTHER", "Other", "📦"),
    )
    for position, (code, name, icon) in enumerate(default_expense_categories):
        if session.scalar(select(ExpenseCategory).where(ExpenseCategory.code == code)) is None:
            session.add(ExpenseCategory(code=code, name=name, icon=icon, sort_order=position * 10))

    owner_role = roles["OWNER"]
    for telegram_id in settings.owner_telegram_ids:
        user = session.scalar(select(User).where(User.telegram_user_id == telegram_id))
        if user is None:
            user = User(telegram_user_id=telegram_id, display_name=f"Owner {telegram_id}")
            session.add(user)
            session.flush()
            session.add(UserRole(user_id=user.id, role_id=owner_role.id))
            append_audit(session, action="OWNER_BOOTSTRAPPED", entity_type="user", entity_id=str(user.id), actor=user, new_values={"telegram_user_id": telegram_id, "role": "OWNER"})
