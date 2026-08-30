from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parse_time(name: str, default: str) -> time:
    raw = os.getenv(name, default).strip()
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM format") from exc


def _parse_ids(raw: str) -> tuple[int, ...]:
    if not raw.strip():
        return ()
    try:
        values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError("OWNER_TELEGRAM_IDS must contain only comma-separated numeric IDs") from exc
    if any(value <= 0 for value in values):
        raise ValueError("OWNER_TELEGRAM_IDS must contain positive numeric IDs")
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Settings:
    shop_name: str
    timezone_name: str
    official_open_time: time
    official_close_time: time
    late_reminder_time: time
    database_url: str
    owner_telegram_ids: tuple[int, ...]
    supported_currencies: tuple[str, ...]
    backup_directory: Path
    backup_retention_days: int
    telegram_bot_token: str = ""
    enable_same_currency_split: bool = True
    telegram_bot_username: str = "TnoatTum_Cafe_bot"
    expense_within_limit_posts_immediately: bool = False
    require_receipt_for_all_expenses: bool = True
    expense_attachment_directory: Path = Path("receipts")
    max_expense_attachment_bytes: int = 10_000_000
    closing_tolerance_khr_minor: int = 0
    closing_tolerance_usd_minor: int = 0
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    dashboard_session_minutes: int = 30
    dashboard_access_token: str = ""

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    timezone_name = os.getenv("SHOP_TIMEZONE", "Asia/Phnom_Penh")
    ZoneInfo(timezone_name)
    currencies = tuple(code.strip().upper() for code in os.getenv("SUPPORTED_CURRENCIES", "KHR,USD").split(",") if code.strip())
    if currencies != ("KHR", "USD"):
        raise ValueError("Phase 0 requires SUPPORTED_CURRENCIES=KHR,USD in that order")
    retention = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    if retention < 1:
        raise ValueError("BACKUP_RETENTION_DAYS must be positive")
    max_attachment_bytes = int(os.getenv("MAX_EXPENSE_ATTACHMENT_BYTES", "10000000"))
    if max_attachment_bytes < 1:
        raise ValueError("MAX_EXPENSE_ATTACHMENT_BYTES must be positive")
    return Settings(
        shop_name=os.getenv("SHOP_NAME", "Tnoat Tum Cafe").strip(),
        timezone_name=timezone_name,
        official_open_time=_parse_time("OFFICIAL_OPEN_TIME", "08:00"),
        official_close_time=_parse_time("OFFICIAL_CLOSE_TIME", "17:00"),
        late_reminder_time=_parse_time("LATE_REMINDER_TIME", "18:00"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/tnoat_tum_cafe.sqlite3"),
        owner_telegram_ids=_parse_ids(os.getenv("OWNER_TELEGRAM_IDS", "")),
        supported_currencies=currencies,
        backup_directory=Path(os.getenv("BACKUP_DIRECTORY", "backups")),
        backup_retention_days=retention,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        enable_same_currency_split=os.getenv("ENABLE_SAME_CURRENCY_SPLIT", "true").strip().lower() in {"1", "true", "yes", "on"},
        telegram_bot_username=os.getenv("TELEGRAM_BOT_USERNAME", "TnoatTum_Cafe_bot").strip().lstrip("@"),
        expense_within_limit_posts_immediately=os.getenv("EXPENSE_WITHIN_LIMIT_POSTS_IMMEDIATELY", "false").strip().lower() in {"1", "true", "yes", "on"},
        require_receipt_for_all_expenses=os.getenv("REQUIRE_RECEIPT_FOR_ALL_EXPENSES", "true").strip().lower() in {"1", "true", "yes", "on"},
        expense_attachment_directory=Path(os.getenv("EXPENSE_ATTACHMENT_DIRECTORY", "receipts")),
        max_expense_attachment_bytes=max_attachment_bytes,
        closing_tolerance_khr_minor=int(os.getenv("CLOSING_TOLERANCE_KHR", "0")),
        closing_tolerance_usd_minor=int(os.getenv("CLOSING_TOLERANCE_USD_CENTS", "0")),
        dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", "8000")),
        dashboard_session_minutes=int(os.getenv("DASHBOARD_SESSION_MINUTES", "30")),
        dashboard_access_token=os.getenv("DASHBOARD_ACCESS_TOKEN", "").strip(),
    )
