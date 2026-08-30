# Tnoat Tum Cafe — New PC Setup

GitHub synchronizes source code. It does **not** back up or transfer the live financial database.

## First-time setup

1. Install Git for Windows and 64-bit Python 3.11 or newer. During Python installation, enable the Python launcher.
2. In PowerShell, choose a safe empty parent folder and run:

   ```powershell
   git clone https://github.com/bunthorngnop/Tnoatum.git "Tnoat-Tum-Cafe"
   cd "Tnoat-Tum-Cafe"
   ```

3. Confirm the checked-out branch is `main`, then double-click `SETUP_OR_PULL_FROM_GITHUB.bat`.
4. Open `.env` in VS Code and enter the locally required numeric owner Telegram ID(s) and bot token. Never send or commit this file.
5. In the VS Code terminal, activate the environment and bootstrap the configured owner:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m tnoat_tum_cafe.cli bootstrap
   ```

6. Follow `docs/TELEGRAM_SETUP.md` to load an owner-verified catalog, configure owner-approved expense policies, open the business day, confirm opening cash, and start the bot.
7. Set a unique local `DASHBOARD_ACCESS_TOKEN`, run `python -m tnoat_tum_cafe.cli run-dashboard`, and open `http://127.0.0.1:8000`.

## Updating an existing PC

Close the running app, confirm your source tree has no uncommitted work, then double-click `SETUP_OR_PULL_FROM_GITHUB.bat`. It uses fast-forward-only pull and Alembic migrations. It does not replace the live database.

## Live financial data

Do not copy a database over an active database. Phase 6 will add verified database backup/restore tooling and retention. Until then, database restoration is not an owner-safe automated workflow.

Phase 3 database setup is included in the normal migration step. After setup, an authorized owner can open Telegram and use `/cash`. Do not copy a live SQLite database through GitHub; source synchronization and financial-data backup remain separate systems.
