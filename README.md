# Tnoat Tum Cafe

Phase 2 local-Windows-first Telegram sales and controlled-expense system. The authoritative requirements are in `TNOAT_TUM_CAFE_CODEX_MASTER_BUILD_PROMPT.md`.

## Current scope

Implemented: the Phase 0/1 foundation plus configurable expense categories and authority limits, exact KHR/USD expenses, Cash/ABA separation, receipt attachments, pending approvals, owner approve/reject/ask-question flows, requester replies/notifications, immutable expense history, and controlled reversals.

Not yet implemented: opening/expected cash, final closing, dashboard, automated DB backup/restore, OCR, voice, or AI.

## Local installation

Install 64-bit Python 3.11+ and Git for Windows, then run in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m tnoat_tum_cafe.cli bootstrap
python -m tnoat_tum_cafe.cli health
```

Before `bootstrap`, edit `.env` and set `OWNER_TELEGRAM_IDS` to owner-approved numeric IDs. `TELEGRAM_BOT_TOKEN` is reserved for Phase 1 and must remain local.

## Phase 1 setup and bot

The included `config/demo_catalog.json` is visibly marked sample/demo and is never loaded automatically. To test it locally after setting the owner ID:

```powershell
python -m tnoat_tum_cafe.cli bootstrap
python -m tnoat_tum_cafe.cli import-catalog config\demo_catalog.json --demo --actor-telegram-id YOUR_OWNER_ID
python -m tnoat_tum_cafe.cli open-day --actor-telegram-id YOUR_OWNER_ID
python -m tnoat_tum_cafe.cli run-bot
```

Import a real catalog only after owner verification:

```powershell
python -m tnoat_tum_cafe.cli import-catalog path\verified_catalog.json --verified --actor-telegram-id YOUR_OWNER_ID
```

Add an authorized staff identity:

```powershell
python -m tnoat_tum_cafe.cli add-user --telegram-id STAFF_NUMERIC_ID --name "Staff Name" --role STAFF --actor-telegram-id YOUR_OWNER_ID
```

Add an owner-approved discount preset:

```powershell
python -m tnoat_tum_cafe.cli add-discount 5 --actor-telegram-id YOUR_OWNER_ID
```

See `docs/TELEGRAM_SETUP.md` for the complete manual flow.

## Phase 2 expense configuration

No monetary expense limit is assumed. Configure owner-approved limits explicitly:

```powershell
python -m tnoat_tum_cafe.cli set-expense-limit --role STAFF --currency KHR --amount OWNER_APPROVED_AMOUNT --actor-telegram-id 166792174
python -m tnoat_tum_cafe.cli set-expense-limit --role STAFF --currency USD --amount OWNER_APPROVED_AMOUNT --actor-telegram-id 166792174
```

User-specific limits override role limits:

```powershell
python -m tnoat_tum_cafe.cli set-expense-limit --user-telegram-id STAFF_NUMERIC_ID --currency KHR --amount OWNER_APPROVED_AMOUNT --actor-telegram-id 166792174
```

Configure category receipt policy:

```powershell
python -m tnoat_tum_cafe.cli set-expense-category-receipt --category-code REPAIR --required true --actor-telegram-id 166792174
```

The safest `.env.example` policy keeps within-limit expenses pending and requires receipts globally. Change these only with owner approval:

```env
EXPENSE_WITHIN_LIMIT_POSTS_IMMEDIATELY=false
REQUIRE_RECEIPT_FOR_ALL_EXPENSES=true
```

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest
```

## Database and migrations

The default runtime database is `data/tnoat_tum_cafe.sqlite3`, excluded from Git. Apply safe forward migrations with:

```powershell
python -m alembic upgrade head
```

Migration `0001_phase0_foundation` creates identity and audit foundations. Migration `0002_phase1_sales` adds sales. Migration `0003_phase2_expenses` adds categories, limits, requests, attachments, approval events, expenses, corrections, and durable notification outbox records. Never edit financial history directly or replace a live database during a source update.

## GitHub workflows

- Confirmed source repository: `https://github.com/bunthorngnop/Tnoatum.git`
- Default branch: `main`
- `PUSH_TO_GITHUB.bat`: checks Git/remote, fetches, refuses remote divergence and sensitive staged paths, then commits and pushes without force.
- `SETUP_OR_PULL_FROM_GITHUB.bat`: fast-forward-only source update, environment setup, migrations, tests, and health check without replacing a live DB.
- `NEW_PC_SETUP.md`: owner-friendly clone and setup instructions.

Git credentials are configured independently on each PC; never put credentials in the repository URL or source files.

## Backup and restore

GitHub is not a financial database backup. The runtime DB and `backups/` are ignored. Automated versioned backup, retention, verification, and safe restore instructions belong to Phase 6 and are not yet implemented.

## Owner/admin and Telegram setup

Numeric Telegram user IDs are authoritative. `/myid` reports the sender's numeric ID but grants no access. All other flows require an active configured user. Secrets remain in `.env`; Telegram long polling starts with `python -m tnoat_tum_cafe.cli run-bot`.
