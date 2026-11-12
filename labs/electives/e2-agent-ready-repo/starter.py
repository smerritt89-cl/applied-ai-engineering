"""Order pricing for a small B2B storefront (the sample repo's application code).

In this lab you don't edit this file yourself. It is the code a coding agent will
work on. `make_workspace.py` copies it into a fresh workspace as `pricing.py`.

Rules the business agreed on (see the ticket in the workspace README):

- All money is integer cents. Never use floats for money.
- Bulk discount by quantity on each line: 10 or more units 5% off, 50 or more 10%,
  100 or more 15%. The discount is rounded half up to the nearest cent.
- Promo codes apply to the subtotal after bulk discounts. Codes are case-insensitive
  and surrounding whitespace is ignored. Expired or unknown codes are rejected.
- Tax applies to the discounted subtotal and is rounded half up to the nearest cent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# (minimum quantity, percent off), checked from the largest tier down
BULK_TIERS = [(100, 15), (50, 10), (10, 5)]

PROMO_CODES = {
    "WELCOME10": {"percent": 10, "expires": date(2027, 1, 31)},
    "SPRING5": {"percent": 5, "expires": date(2026, 5, 31)},
    "VIP20": {"percent": 20, "expires": None},
}


class PricingError(ValueError):
    """Raised for invalid input or a promo code that can't be applied."""


@dataclass(frozen=True)
class LineItem:
    sku: str
    quantity: int
    unit_price_cents: int


def percent_of(amount_cents: int, percent: int) -> int:
    """Return percent% of amount_cents, rounded half up to a whole cent."""
    return int(round(amount_cents * percent / 100))


def bulk_discount_percent(quantity: int) -> int:
    """Percent off for a line with this many units."""
    for min_quantity, percent in BULK_TIERS:
        if quantity > min_quantity:
            return percent
    return 0


def line_total_cents(item: LineItem) -> int:
    """Price of one line after its bulk discount."""
    if item.quantity <= 0:
        raise PricingError(f"quantity must be positive for {item.sku}")
    if item.unit_price_cents < 0:
        raise PricingError(f"price must not be negative for {item.sku}")
    gross = item.quantity * item.unit_price_cents
    return gross - percent_of(gross, bulk_discount_percent(item.quantity))


def promo_percent(code: str, today: date) -> int:
    """Percent off for a promo code on the given day. Raises PricingError if it can't be used."""
    promo = PROMO_CODES.get(code)
    if promo is None:
        raise PricingError(f"unknown promo code: {code!r}")
    expires = promo["expires"]
    if expires is not None and today > expires:
        raise PricingError(f"promo code {code!r} expired on {expires.isoformat()}")
    return promo["percent"]


def order_total_cents(
    items: list[LineItem],
    promo_code: str | None = None,
    tax_rate_percent: int = 0,
    today: date | None = None,
) -> int:
    """Total for an order: line totals, then the promo, then tax."""
    if not items:
        raise PricingError("an order needs at least one line item")
    today = today or date.today()
    subtotal = sum(line_total_cents(item) for item in items)
    if promo_code:
        subtotal -= percent_of(subtotal, promo_percent(promo_code, today))
    return subtotal + percent_of(subtotal, tax_rate_percent)
