# Deterministic Local Convenience

Version 1 uses only local SQL, counts, grouping, and Python fuzzy matching. No paid or hosted AI API is required.

Features include personal favorites (`/favorite PRODUCT_ID`), recent/frequent products, common historical OPEN_PRICE amounts, owner-managed aliases, safe fuzzy lookup, busiest hours, discount/correction/expense indicators, staff activity counts, and `/insights` for authorized owners. The dashboard exposes `/api/insights` with an authorized numeric Telegram actor header.

Repeated manual item names create advisory `Add to Quick Menu` suggestions after three uses. Accepting or ignoring a suggestion records a decision and audit evidence; it never silently creates a product or official price.
