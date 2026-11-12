"""The sample repo's own test suite.

In the lab folder these tests import from `starter` (the buggy module), so four of
them fail: that is the task you hand to a coding agent. `make_workspace.py` copies
this file into the workspace as tests/test_pricing.py and rewrites the import to
`pricing`. Run here with:  pytest electives/e2-agent-ready-repo -q
"""
from datetime import date

import pytest

from starter import LineItem, PricingError, line_total_cents, order_total_cents

TODAY = date(2026, 11, 11)


# ---------------------------------------------------------------- bulk discounts


def test_no_bulk_discount_below_ten_units():
    assert line_total_cents(LineItem("PEN", 9, 100)) == 900


def test_bulk_discount_starts_at_ten_units():
    # Ticket #142: a customer ordered exactly 10 units and was charged full price.
    assert line_total_cents(LineItem("PEN", 10, 100)) == 950


def test_fifty_unit_tier():
    assert line_total_cents(LineItem("PEN", 60, 100)) == 5400


def test_bulk_discount_rounds_half_up():
    # 14 x 35 = 490 cents; 5% is 24.5 cents, which rounds up to 25.
    assert line_total_cents(LineItem("CLIP", 14, 35)) == 465


# ---------------------------------------------------------------- promo codes


def test_promo_code_is_case_insensitive_and_trimmed():
    # Ticket #142 again: "welcome10 " was rejected at checkout.
    items = [LineItem("BINDER", 1, 1000)]
    assert order_total_cents(items, promo_code="welcome10 ", today=TODAY) == 900


def test_expired_promo_is_rejected():
    with pytest.raises(PricingError, match="expired"):
        order_total_cents([LineItem("BINDER", 1, 1000)], promo_code="SPRING5", today=TODAY)


def test_unknown_promo_is_rejected():
    with pytest.raises(PricingError, match="unknown"):
        order_total_cents([LineItem("BINDER", 1, 1000)], promo_code="FREESTUFF", today=TODAY)


# ---------------------------------------------------------------- whole orders


def test_order_with_promo_and_tax():
    items = [LineItem("STAPLER", 2, 1999), LineItem("TAPE", 1, 500)]
    # subtotal 4498; WELCOME10 takes 450; 8% tax on 4048 is 323.84, so 324
    assert order_total_cents(items, promo_code="WELCOME10", tax_rate_percent=8, today=TODAY) == 4372


def test_tax_rounds_half_up():
    # 1% of 650 cents is 6.5 cents, which rounds up to 7.
    assert order_total_cents([LineItem("BOARD", 1, 650)], tax_rate_percent=1, today=TODAY) == 657


# ---------------------------------------------------------------- safeguards


def test_rejects_non_positive_quantity():
    with pytest.raises(PricingError):
        line_total_cents(LineItem("PEN", 0, 100))


def test_rejects_negative_price():
    with pytest.raises(PricingError):
        line_total_cents(LineItem("PEN", 1, -5))


def test_rejects_empty_order():
    with pytest.raises(PricingError):
        order_total_cents([], today=TODAY)
