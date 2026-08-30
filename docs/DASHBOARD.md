# Owner Dashboard

The dashboard is local-only by default at `http://127.0.0.1:8000`. Generate a long random local access token and store it in `.env` as `DASHBOARD_ACCESS_TOKEN`. Never commit it.

Start with `python -m tnoat_tum_cafe.cli run-dashboard`. Login sessions expire according to `DASHBOARD_SESSION_MINUTES`. Do not bind to a network/public address without an owner-approved deployment and stronger network controls.

Available views/APIs cover today, date-range reports, separate KHR/USD Cash and ABA/KHQR, expenses and pending approvals, products and suggested prices, discounts, users, roles, permissions, closing discrepancies, and audit history. No reporting conversion is performed without a future explicit exchange-rate policy.
