# Database Backup and Recovery

GitHub contains source only. It is never the financial database backup.

The bot and dashboard attempt one verified local SQLite backup per UTC day at startup. `BACKUP_DIRECTORY` and `BACKUP_RETENTION_DAYS` are configurable. Create one manually with `python -m tnoat_tum_cafe.cli backup-db --actor-telegram-id 166792174`. Verify with `python -m tnoat_tum_cafe.cli verify-backup PATH`.

## Safe restore

1. Stop the Telegram bot and dashboard.
2. Preserve the existing live database under a separate owner-controlled name/location.
3. Restore only to a path that does not exist:
   `python -m tnoat_tum_cafe.cli restore-backup BACKUP_PATH NEW_DATABASE_PATH`
4. Point a temporary `DATABASE_URL` at the restored copy.
5. Run `python -m alembic upgrade head`, `python -m tnoat_tum_cafe.cli health`, and `python -m pytest`.
6. Inspect users, business days, recent sales, expenses, cash, and closings before adopting it as live data.

Restore refuses to overwrite any existing target. Both source and restored databases receive SQLite integrity checks. Test restores must use test data only.
