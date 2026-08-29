# Telegram Phase 1 Setup and Manual Test

## Credentials and identities

1. The confirmed bot username is `@TnoatTum_Cafe_bot`. Manage its private token through Telegram `@BotFather`.
2. Put the token only in local `.env` as `TELEGRAM_BOT_TOKEN=...`.
3. Send `/myid` to the bot to display your numeric Telegram ID. This command grants no access.
4. Put the approved owner ID in `OWNER_TELEGRAM_IDS`, then run `python -m tnoat_tum_cafe.cli bootstrap`.
5. Add staff with the `add-user` command documented in `README.md`.

Never paste a token into source, documentation, Git, screenshots, or logs. If exposed, revoke it through `@BotFather`.

## Prepare a safe demo

The demo catalog is separate from production and clearly labeled. It is not the official menu.

```powershell
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
python -m tnoat_tum_cafe.cli bootstrap
python -m tnoat_tum_cafe.cli import-catalog config\demo_catalog.json --demo --actor-telegram-id YOUR_OWNER_ID
python -m tnoat_tum_cafe.cli open-day --actor-telegram-id YOUR_OWNER_ID
python -m tnoat_tum_cafe.cli run-bot
```

## Telegram test flow

1. Send `/start` and tap `🧾 NEW SALE`.
2. Test the demo fixed-price item and quantities 1–5.
3. Test the open-price item with KHR and USD input separately.
4. Test `✍️ Custom Item`, name, currency, price, and quantity.
5. Add multiple same-currency items to the cart. Mixed KHR/USD items are intentionally rejected.
6. Choose a configured discount, then Cash, ABA/KHQR, or same-currency split.
7. Review the full total and payment before tapping Confirm.
8. Tap Confirm repeatedly; only one sale must post.
9. Open `👤 MY ACCOUNT`; only your activity should appear.
10. Use `Correct Last Sale`, enter a reason, and verify the receipt becomes reversed without disappearing.

ABA/KHQR ledger entries remain distinct from Cash. Cross-currency split payment stays disabled until an explicit exchange-rate policy is approved.

## Tests without Telegram

```powershell
python -m pytest
python -m tnoat_tum_cafe.cli health
```
