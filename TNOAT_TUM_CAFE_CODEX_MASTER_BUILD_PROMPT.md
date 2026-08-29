# TNOAT TUM CAFE — AUTHORITATIVE CODEX MASTER BUILD PROMPT

**Project:** Telegram Finance, Sales, Expense Approval & Daily Closing System  
**Timezone:** Asia/Phnom_Penh (UTC+7)  
**Currencies:** KHR + USD  
**Official hours:** 08:00–17:00; actual service may continue until 22:00, midnight, or later  
**AI policy:** ZERO PAID AI API DEPENDENCY  
**Principle:** Simple for staff. Strict with money. Transparent for the owner. Ready to grow.

## 0. CODEX KEYWORDS
**MUST/MUST NOT** are mandatory. **SHOULD** is strongly recommended. **AUTHORITATIVE** means this file is the source of truth unless explicitly amended by the owner. **DO NOT ASSUME** means never invent prices, IDs, credentials, limits, financial rules, or integrations. **NEEDS OWNER DECISION** means use the safest configurable behavior and report the unresolved choice. **STOP** means stop after the requested phase and wait.

Read this entire file before changing code. Preserve existing data and working features. Never silently discard financial history.

## 1. MISSION
Build a local-Windows-first system for **Tnoat Tum Cafe** where Telegram is the primary staff interface and the owner also has a private Telegram command center plus a local web dashboard.

Core capabilities:
- button-driven sales;
- fixed-price coffee/menu products;
- open-price food/drinks;
- completely custom items;
- cart/multi-item sales;
- discounts;
- KHR/USD cash;
- ABA/KHQR;
- staff personal activity;
- controlled expenses;
- Telegram owner approval for over-limit expenses;
- opening cash;
- reconciliation/closing;
- automatic owner closing notification;
- immutable audit history;
- reports/backups;
- two mandatory one-click GitHub workflows;
- attractive Tnoat Tum Cafe branding/icons;
- smart local conveniences without paid AI.

> Staff mostly tap buttons. The system does the accounting.

## 2. BRANDING & UX
Use the supplied Tnoat Tum Cafe logo as the branding reference when available in project assets. UI must be friendly, attractive, fast, Khmer-Unicode-safe, and suitable for nontechnical staff.

Use consistent Telegram-native icons/emojis, e.g. ☕ coffee, 🍚 food, 🥤 drinks, 🧾 sale, 🛒 cart, 🏷️ discount, 💵 cash, 🇰🇭 KHR, 🇺🇸 USD, 📱 ABA/KHQR, 💸 expense, 📷 receipt, ⏳ pending, ✅ approve, ❌ reject, ⚠️ warning, 🌅 open, 🌙 closing, 🔒 close, 👤 account, 👥 staff, 📊 reports, 👑 owner, ⚙️ settings, 💾 backup, ☁️ GitHub.

Centralize user-facing strings for future Khmer/English localization.

## 3. BUSINESS DAY
Official hours are 08:00–17:00, but customers may remain much later.

MUST:
- never auto-close at 17:00;
- allow Continue Service or Start Closing after official hours;
- keep business day open until authorized explicit close;
- separate business date from calendar date;
- if service crosses midnight, attach later transactions to the still-open originating business day;
- never silently split at midnight;
- allow late-open owner reminder;
- use states such as OPEN -> CLOSING_PENDING -> CLOSED;
- audit cancellation of closing/reopening of closed day.

## 4. USERS & PERMISSIONS
Telegram numeric user ID is authoritative.

**Staff:** sales, fixed/open/manual products, permitted discounts, own account, permitted expenses, over-limit approval requests, receipts, permitted corrections. No hard deletion or unauthorized administration.

**Cashier:** staff capabilities plus configurable opening cash, cash count, handover, closing.

**Manager:** configurable higher expense/discount/correction/closing authority and operational oversight.

**Owner/Admin:** full control, approvals, products/prices, users/permissions, settings, reports, audit, closings, backups.

Permissions must be configurable, not only hard-coded by role.

## 5. PRICING MODES
Support:
1. `FIXED_PRICE` — official menu button with known price. Staff should not type name/normal price.
2. `OPEN_PRICE` — known button, flexible price, optionally suggested quick-price buttons.
3. `MANUAL_ITEM` — staff enters custom item name, price, quantity.

The printed menu has many items around 4,000៛ and 6,000៛, but **DO NOT ASSUME exact item-price mappings**. Owner/admin must verify/edit the catalog. Historical sales preserve the price used at sale time.

Suggested OPEN_PRICE food buttons may include White Rice, Fried Rice, Pork/Beef/Chicken & Rice, Fried Noodles, Noodle Soup, Kuy Teav, Rice Porridge, Soup, Beef Soup, Chicken Soup, Egg, Made-to-order Dish, Other Food.

Suggested custom drinks may include Orange, Lime, Honey Lime, Milk Tea, Lemon Tea, Fruit Tea, Fruit/Avocado/Mango/Coconut Smoothie, Chocolate, Matcha, Soda Mix, Other Drink.

These names/buttons are configurable and must not receive invented official prices.

## 6. SALES
Primary flow:
`NEW SALE -> Add item(s) -> Quantity -> Price if needed -> Discount -> Payment -> Review -> Confirm`

MUST support a cart so one customer can buy multiple items. Use quick quantity buttons such as 1–5 + Other. No financial posting until final confirmation. Telegram retries/repeated taps must not duplicate sales.

## 7. DISCOUNTS
Provide configurable quick buttons such as None, 5%, 10%, 15%, 20%, Custom. Store original subtotal, discount, final total, actor and approval where applicable. Owner may configure thresholds requiring manager/owner approval. Do not assume a threshold.

## 8. CURRENCY & PAYMENTS
KHR and USD are first-class and remain separate. Never silently convert. Optional reporting conversion may use an explicit configured exchange rate while preserving original amounts.

Minimum payment methods: Cash and ABA/KHQR. Architecture may support Bank Transfer/Other later. ABA/KHQR does not increase physical drawer cash.

Support optional split payment. Payment allocations must exactly equal amount due. Do not enable cross-currency split without an explicit exchange-rate policy.

## 9. STAFF ACCOUNT
Provide `👤 MY ACCOUNT`: own transactions, fixed/open/manual sales, KHR cash, USD cash, ABA/KHQR, discounts, corrections and permitted expense activity. Staff may inspect but not rewrite history. Owner sees all staff activity. Profit/margin can remain owner-only.

## 10. IMMUTABLE HISTORY
Posted sales, payments, expenses, approvals, cash movements and closings must not be hard-deleted. Corrections use void/reversal/adjustment/replacement while preserving original, reason, actor, approver, timestamps and linkage. A friendly `Correct Last Sale` button may wrap this controlled process.

## 11. EXPENSES
Telegram expense entry should capture category, amount, currency, payment source, reason, requester, receipt/photo, status and timestamps.

Configurable categories may include Ingredients, Ice, Milk, Food Supplies, Delivery, Repair, Utilities, Other.

Payment source must distinguish KHR Cash, USD Cash, ABA/KHQR/configured bank source. Posted cash expense reduces corresponding expected cash.

## 12. EXPENSE LIMITS & BOT APPROVAL
Limits are configurable by role/user and currency. `$10` is an example only—never hard-code it.

Within-authority expense may post according to policy. Over-limit expense becomes `PENDING` and is not an official posted expense until approved.

Owner/admin receives private Telegram request containing request ID, requester, amount/currency, category, reason, payment source, receipt status, configured limit, and buttons:
`✅ APPROVE | ❌ REJECT | 💬 ASK QUESTION`

Only authorized numeric Telegram IDs can decide. Requester cannot approve own prohibited request. Approval posts exactly once, records approver/time, and notifies requester. Rejection posts no official expense but remains auditable. Duplicate/stale callbacks must be harmless. Optional 🚨 URGENT marks priority but never bypasses control.

## 13. OPENING & EXPECTED CASH
Authorized opening records KHR and USD opening floats separately.

KHR expected cash =
opening KHR + KHR cash sales + deposits - KHR cash expenses - refunds - withdrawals +/- authorized adjustments.

USD follows the same independent logic.

ABA/KHQR never changes physical cash.

## 14. DAILY CLOSING
Closing workflow:
1. start closing;
2. count actual KHR;
3. count actual USD;
4. review/confirm ABA/KHQR;
5. review expenses/cash movements;
6. calculate expected vs actual;
7. show differences;
8. require explanation above configured tolerance;
9. confirm;
10. close business day;
11. privately notify owner/admin.

Preserve business date, real close timestamp, closing staff, expected/actual/difference for KHR and USD independently, ABA/KHQR, expenses, explanations and audit metadata. Never manipulate transactions merely to force a match.

## 15. OWNER CLOSING NOTIFICATION
Immediately after close, send branded private Telegram report with business date, closer, close time, sales/payment breakdown, expenses, KHR/USD expected vs actual, differences/warnings, ABA/KHQR and button/link to full report.

## 16. OWNER WITHDRAWAL / NEXT-DAY FLOAT
Explicitly record owner withdrawals and retained float. Example: closing 850,000៛, retain 300,000៛, owner withdrawal 550,000៛. Money must not simply disappear. Next opening may suggest retained float. Support USD equivalently.

## 17. OWNER TELEGRAM & WEB DASHBOARD
Owner Telegram command center should include Pending Approvals, Today Finance, Cash Status, Staff Activity, Expenses, Closing Reports, Alerts, Settings.

Local responsive web dashboard should support daily/weekly/monthly reporting, KHR/USD/ABA breakdown, staff, expenses/approvals, closings/discrepancies, products/prices/suggested prices, discounts, expense limits, users/permissions, audit, backup status, business-day history and useful charts.

## 18. ZERO-PAID-AI SMART FEATURES
Core operation MUST NOT depend on OpenAI/Anthropic/Gemini or any paid inference API.

Use deterministic/local logic for favorites, recent items, frequently sold items, common open prices, aliases/fuzzy matching, trends, busiest hours, unusual discounts/corrections/expenses and staff statistics.

Repeated manual items may trigger an owner recommendation: `Add to Quick Menu | Ignore`. Never silently alter official menu/prices.

Ollama/llama.cpp/Tesseract/local models are future optional features only. Version 1 works fully without them.

## 19. DATA MODEL
Design normalized entities covering users, roles, permissions, categories/products/aliases/suggested prices, discount rules, currencies/payment methods, business days, sales/items/discounts/payments, ledger entries, expenses/categories/approval requests/events, attachments, cash movements/counts, closings, audit logs, settings, idempotency records and backup metadata.

Future-compatible inventory/recipes/suppliers may be modeled later but not implemented now.

Use exact money types: integer riel for KHR preferred; exact decimal/minor-unit handling for USD. Never binary floating-point for money.

## 20. LEDGER
Every posted money movement identifies type/direction, amount, currency, source/payment method, business day, source entity, actor and timestamp. Distinguish sales revenue, cash receipts, ABA receipts, expenses, refunds, withdrawals, deposits, adjustments and reversals.

Do not claim formal double-entry accounting unless actually implemented/tested.

## 21. AUDIT
Audit actor, identity, action, entity, timestamp, old/new values where relevant, reason, approver and correlation/request ID. Include sales, discounts, manual prices, expenses/decisions, product-price changes, reversals, opening/closing/reopening, permissions/settings. Audit history must not be casually editable.

## 22. TECHNICAL BASELINE
Preferred unless existing code safely dictates otherwise:
- Python 3
- maintained Python Telegram library / Telegram Bot API
- FastAPI
- SQLite
- SQLAlchemy
- Alembic/equivalent migrations
- HTML/CSS/JS + lightweight Bootstrap-like UI
- pytest
- `.env`
- Windows-first scripts

Long polling is acceptable/preferred for simple local Telegram operation. Separate Telegram/UI adapters from business/domain logic and persistence.

## 23. SECURITY & RELIABILITY
MUST:
- keep secrets in `.env`;
- `.gitignore` secrets, runtime DB, logs and sensitive backups;
- authorize privileged Telegram callbacks by numeric ID;
- validate money/input/state;
- use DB transactions for multi-step posting;
- implement idempotency;
- survive retries/restarts safely;
- never expose tokens in logs;
- protect dashboard;
- avoid destructive migrations;
- fail without partial financial posting.

Handle duplicate updates, repeated taps, abandoned workflows, restart, invalid amounts, unauthorized/stale callbacks, already-decided approvals, closed-day corrections, migration and backup failures.

## 24. BACKUP
GitHub source synchronization is **not** accounting backup.

Implement separate automatic daily local DB backups with timestamped generations, configurable retention, restore documentation and verification where practical. Never commit live DB/backups to public GitHub by default.

## 25. PERMANENT MANDATORY TWO ONE-CLICK GITHUB FILES
This requirement MUST remain in every authoritative master specification.

### `PUSH_TO_GITHUB.bat`
One-click safe source-project synchronization. Verify Git/repo/remote/status; stage appropriate source; never stage ignored secrets/runtime finance data; commit with simple timestamp/default or easy prompt; safely account for remote divergence; push; show SUCCESS/ERROR and pause.

MUST NOT upload `.env`, tokens, passwords, live financial DB/backups; force-push; automatically use destructive reset; silently overwrite remote work.

### `SETUP_OR_PULL_FROM_GITHUB.bat`
For an existing clone, one click safely pulls/updates and validates/setup dependencies. For a brand-new PC, provide the simplest possible bootstrap path to clone first, then run this script.

It should verify Git/Python, clone/pull as appropriate, create/reuse venv, install dependencies, create folders, check `.env`, clearly identify locally required secrets, run safe migrations/setup, run health checks, never overwrite a live DB, show SUCCESS/ERROR and pause.

Also create `NEW_PC_SETUP.md` with very simple owner-friendly instructions.

GitHub credentials are not assumed transferable between PCs. Preserve live data during software updates.

## 26. CONFIGURATION
Centralize shop name, timezone, official hours, late reminder, currencies, reporting exchange rate, products/prices/suggested prices, discount presets/thresholds, expense categories/limits, receipt rules, discrepancy tolerances, owner Telegram IDs, permissions and backup retention. Do not scatter business constants.

## 27. REPORTS
Daily: sales by currency/payment, fixed/open/manual mix, discounts, expenses, cash movements, expected/actual cash, discrepancy, staff activity, closing.

Period: date range, weekly/monthly, product performance, payment mix, expenses, staff, discounts/corrections, discrepancies.

Never show a misleading combined KHR/USD figure without original amounts and explicit exchange rate.

## 28. TESTS
Automated tests must cover at least:

**Sales:** fixed/open/manual, cart, quantity, discounts, KHR cash, USD cash, ABA, split payment, duplicate callback.

**Expenses:** within limit, over-limit pending, unauthorized/self approval blocked, owner approval posts once, rejection posts none, duplicate approval harmless, correct currency cash impact.

**Closing:** opening KHR/USD, expected calculations, ABA excluded from drawer, discrepancy/tolerance/explanation, late close, cross-midnight business day, withdrawal/float, closing notification data.

**Audit/security:** reversal preserves original, permissions, historical price preservation, secrets/runtime data excluded from Git.

Run regression tests after each phase. Never claim a test passed unless executed.

## 29. DEVELOPMENT PHASES
**Phase 0 Foundation:** structure, config, `.env.example`, `.gitignore`, DB/migrations, users/permissions, Telegram identity, business day, audit, tests, GitHub helper skeleton.

**Phase 1 Sales:** attractive Telegram menu/icons, fixed/open/manual products, cart, quantity, discounts, KHR/USD, Cash/ABA, confirmation, staff account.

**Phase 2 Expenses:** categories, receipts, limits, pending requests, owner approve/reject/ask, audit.

**Phase 3 Cash:** opening, cash movements, expected cash, withdrawals, retained float.

**Phase 4 Closing:** states, KHR/USD count, ABA review, discrepancy, cross-midnight, final close, owner notification.

**Phase 5 Dashboard/Reports:** owner web dashboard, settings, staff, audit, history, reports.

**Phase 6 Backup/GitHub/Hardening:** DB backup/restore, both `.bat` files, `NEW_PC_SETUP.md`, security/recovery/idempotency/regression.

**Phase 7 Smart Local Convenience:** favorites, recent/frequent items, common-price suggestions, trends, anomaly rules.

Future only: inventory, recipes, suppliers, payroll, loyalty, delivery, tables, OCR, voice, local LLM, advanced forecasting, direct bank integration.

## 30. VERSION 1 DONE
Version 1 requires: authorized users; attractive button UI; fixed/open/manual sales; cart; quantity; discounts; KHR/USD; Cash/ABA; split payment where enabled; staff account; controlled corrections; expenses/limits/Telegram approvals/receipts; opening cash; expected cash; cross-midnight closing; discrepancies; owner close notification; withdrawal/float; owner dashboard/reports/audit; DB backups/restore docs; both one-click GitHub workflows; critical tests; secret protection; clear setup docs.

## 31. DO NOT ASSUME / DO NOT BUILD
Unless explicitly authorized:
- no paid AI;
- no invented official menu prices;
- no invented Telegram IDs/repo credentials;
- no hard-coded $10 limit;
- no 17:00 auto-close;
- no midnight auto-split;
- no KHR/USD merging;
- no ABA-as-cash;
- no hard-delete of posted history;
- no unauthorized self-approval;
- no force-push;
- no committing secrets/live DB/sensitive backups;
- no overwriting live data during update;
- no premature inventory/AI/OCR/voice;
- no unrelated changes.

Mark unresolved safe business rules `NEEDS OWNER DECISION`.

## 32. DOCUMENTATION
Maintain:
- `README.md`
- this authoritative master prompt
- `.env.example`
- `.gitignore`
- `NEW_PC_SETUP.md`
- backup/restore instructions
- test instructions
- owner/admin setup
- Telegram setup
- migration notes.

README must explain install, configure, run bot/dashboard/tests, backup/restore, GitHub push and new-PC setup/update.

## 33. PHASE REPORT FORMAT
After each phase, **STOP** and report:
1. phase completed;
2. files created;
3. files changed;
4. migrations;
5. tests added;
6. exact tests/results;
7. manual test steps;
8. UI notes;
9. security/data-integrity notes;
10. `NEEDS OWNER DECISION` items;
11. whether both GitHub one-click workflows remain valid.

## 34. FIRST-RUN SETUP
Provide safe bootstrap for initial owner/admin Telegram ID, shop settings, timezone, hours, currencies, verified menu/prices, expense limits, discounts, discrepancy tolerance and backup location. Never ship a universal default admin password.

## 35. FOUR CORE LOOPS
**SELL:** Product -> Quantity -> Price if needed -> Discount -> Cash/ABA -> Confirm  
**SPEND:** Expense -> Amount -> Limit check -> Record OR Ask Owner -> Approve/Reject  
**CHECK:** Staff -> My Account | Manager -> Shop Activity | Owner -> Full Control  
**CLOSE:** Count KHR -> Count USD -> Review ABA -> Compare -> Explain -> Close -> Notify Owner

## 36. FINAL PRINCIPLES
1. Simple for staff.
2. Button-first; typing only when needed.
3. Flexible for real Cambodian café operations.
4. KHR/USD are first-class currencies.
5. Cash and ABA are never confused.
6. Every important money action is attributable.
7. Staff flexibility never means erased history.
8. Over-limit spending requires bot-based owner authorization.
9. Closing records reality and informs owner immediately.
10. Business day follows actual service, not midnight.
11. No paid AI required.
12. GitHub source sync and financial backup are separate.
13. Both one-click GitHub workflows are mandatory.
14. Recoverable, testable, understandable.
15. Never sacrifice financial integrity for convenience.

## 37. INITIAL CODEX EXECUTION INSTRUCTION
When first receiving this file:
1. Read it completely.
2. Inspect existing repository.
3. Identify existing stack/files/tests/DB/features.
4. Preserve working code/data.
5. Produce a concise phased implementation plan.
6. Identify `NEEDS OWNER DECISION` items.
7. verify `.gitignore` protects secrets/runtime financial data.
8. verify/create both mandatory GitHub helper workflows.
9. Begin **Phase 0 only** unless owner explicitly authorizes more.
10. Run tests.
11. Report using Section 33.
12. **STOP and wait for the owner's next instruction.**

---
# END
**Tnoat Tum Cafe — Simple for staff. Strict with money. Transparent for the owner. Ready to grow.**
