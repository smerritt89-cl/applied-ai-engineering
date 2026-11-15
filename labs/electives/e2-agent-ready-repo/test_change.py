"""Acceptance tests for CHANGE.md: a cap on how much a promo code can take off.

Run on their own, once you've made the change in work.py:
    pytest electives/e2-agent-ready-repo/test_change.py -q
"""
from datetime import date

import pytest

# Every lab has a module named `starter`. Import THIS lab's copy now, while this
# folder is first on sys.path; importing inside a test would pick up whichever
# lab's `starter` pytest collected last.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).parent))
for _mod in ("starter", "solution"):
    _sys.modules.pop(_mod, None)
import starter as _starter  # noqa: E402  (the learner's file: work.py on the review track)
from starter import LineItem, PricingError, order_total_cents, promo_percent  # noqa: E402

pytestmark = pytest.mark.change

TODAY = date(2026, 11, 11)
# 100 binders at $10.00: 100,000 cents gross, 15% bulk discount, so an 85,000-cent subtotal.
BIG_ORDER = [LineItem("BINDER", 100, 1000)]


# ---------------------------------------------------------------- the new rule


def test_welcome10_is_capped_at_2500_cents():
    # 10% of 85,000 is 8,500, but WELCOME10 takes at most 2,500 off.
    assert order_total_cents(BIG_ORDER, promo_code="WELCOME10", today=TODAY) == 82500


def test_cap_applies_before_tax():
    # 85,000 - 2,500 = 82,500; 8% tax on that is 6,600.
    assert order_total_cents(BIG_ORDER, promo_code="WELCOME10", tax_rate_percent=8, today=TODAY) == 89100


def test_cap_applies_to_a_messy_code_too():
    assert order_total_cents(BIG_ORDER, promo_code="  welcome10 ", today=TODAY) == 82500


def test_every_promo_code_declares_its_cap():
    for code, promo in _starter.PROMO_CODES.items():
        assert "max_off_cents" in promo, f"{code} has no max_off_cents (use None for no cap)"
    assert _starter.PROMO_CODES["WELCOME10"]["max_off_cents"] == 2500
    assert _starter.PROMO_CODES["VIP20"]["max_off_cents"] is None


def test_the_cap_comes_from_the_data_not_a_hard_coded_code(monkeypatch):
    # Give VIP20 a 100-cent cap for this test only. A fix that special-cases "WELCOME10"
    # in code instead of reading max_off_cents fails here.
    monkeypatch.setitem(_starter.PROMO_CODES["VIP20"], "max_off_cents", 100)
    assert order_total_cents([LineItem("BINDER", 1, 1000)], promo_code="VIP20", today=TODAY) == 900


def test_capped_total_is_still_integer_cents():
    total = order_total_cents(BIG_ORDER, promo_code="WELCOME10", tax_rate_percent=7, today=TODAY)
    assert isinstance(total, int)
    assert total == 88275  # 82,500 + 5,775


# ---------------------------------------------------------------- what must not change


def test_small_orders_are_unchanged():
    assert order_total_cents([LineItem("BINDER", 1, 1000)], promo_code="WELCOME10", today=TODAY) == 900


def test_a_discount_exactly_at_the_cap():
    # 10% of 25,000 is exactly 2,500: the cap and the percent agree.
    assert order_total_cents([LineItem("BINDER", 1, 25000)], promo_code="WELCOME10", today=TODAY) == 22500


def test_uncapped_codes_are_unchanged():
    # VIP20 has no cap: 20% of 85,000 is 17,000.
    assert order_total_cents(BIG_ORDER, promo_code="VIP20", today=TODAY) == 68000


def test_capped_codes_still_expire():
    with pytest.raises(PricingError, match="expired"):
        order_total_cents(BIG_ORDER, promo_code="WELCOME10", today=date(2027, 2, 1))


def test_unknown_codes_are_still_rejected():
    with pytest.raises(PricingError, match="unknown"):
        order_total_cents(BIG_ORDER, promo_code="WELCOME25", today=TODAY)


def test_promo_percent_still_returns_the_percent():
    assert promo_percent(" welcome10", TODAY) == 10
