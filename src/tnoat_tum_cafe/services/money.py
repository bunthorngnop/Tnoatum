from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_money(value: str, currency: str) -> int:
    raw = value.strip().replace(",", "")
    if not raw:
        raise ValueError("Amount is required")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be positive")
    if currency == "KHR":
        if amount != amount.to_integral_value():
            raise ValueError("KHR must be entered as whole riel")
        minor = int(amount)
    elif currency == "USD":
        quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if quantized != amount:
            raise ValueError("USD supports at most two decimal places")
        minor = int(quantized * 100)
    else:
        raise ValueError("Unsupported currency")
    if minor <= 0 or minor > 9_000_000_000_000:
        raise ValueError("Amount is outside the supported range")
    return minor


def format_money(amount_minor: int, currency: str) -> str:
    if currency == "KHR":
        return f"{amount_minor:,}៛"
    if currency == "USD":
        return f"${amount_minor / 100:,.2f}"
    raise ValueError("Unsupported currency")


def discount_amount(subtotal_minor: int, basis_points: int) -> int:
    if subtotal_minor <= 0 or not 0 <= basis_points <= 10_000:
        raise ValueError("Invalid discount calculation")
    return (subtotal_minor * basis_points + 5_000) // 10_000

