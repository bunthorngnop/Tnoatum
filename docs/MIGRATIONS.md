# Migration Notes

Apply migrations only after making a separate verified copy of any live financial database. Source pulls and database backups are separate operations.

## Phase 0

- `0001_phase0_foundation`: creates identity/RBAC, business-day, audit, settings, and idempotency foundations.
- The migration is additive and creates new tables only.
- Downgrade exists for development, but must not be run against a database containing operational history.

## Phase 1

- `0002_phase1_sales`: additive catalog, discount, sale, immutable item snapshot, payment, ledger, and correction tables.
- No existing Phase 0 table or data is deleted.
- Sale correction uses new reversal records and ledger outflows; never downgrade a database containing posted sales.
