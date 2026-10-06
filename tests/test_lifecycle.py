"""Retire rules, from README "Hot first, stale last":

A product retires when no retailer has had it in stock for retire_after_days (60) since first seen,
or when every retailer has delisted it for retire_missing_days (7).

The README does not say whether exactly 60 (or 7) days retires, so the boundary cases sit one hour
either side of the limit, where every reading agrees. Time is injected: nothing here reads the real clock.
"""
import pytest

from tcgwatch import lifecycle
from tests.conftest import CLOCK_START

NOW = CLOCK_START
DAY = 86_400
HOUR = 3_600
RETIRE_AFTER = 60
RETIRE_MISSING = 7



def ago(seconds):
    return NOW - seconds


def listing(first_seen, last_in_stock=None, missing_since=None):
    """One retailer's state for the product; arguments are timestamps."""
    return {"first_seen": first_seen, "last_in_stock": last_in_stock, "missing_since": missing_since}


def retired(entries):
    return lifecycle.is_retired(entries, RETIRE_AFTER, RETIRE_MISSING) is not None


# --- retire_after_days: no stock anywhere since first seen ---------------------------------------


@pytest.mark.parametrize(
    "age_seconds, expected",
    [
        (59 * DAY, False),
        (60 * DAY - HOUR, False),
        (60 * DAY + HOUR, True),
        (61 * DAY, True),
    ],
    ids=["59d", "just-under-60d", "just-over-60d", "61d"],
)
def test_never_in_stock_retires_only_after_sixty_days_since_first_seen(age_seconds, expected):
    entries = [listing(first_seen=ago(age_seconds))]

    assert retired(entries) is expected, f"never in stock, first seen {age_seconds / DAY:.2f} days ago"


def test_in_stock_once_resets_the_sixty_day_clock():
    # First seen 100 days ago, last in stock 30 days ago: only 30 days of drought.
    entries = [listing(first_seen=ago(100 * DAY), last_in_stock=ago(30 * DAY))]

    assert not retired(entries)


def test_drought_longer_than_sixty_days_since_last_in_stock_retires():
    entries = [listing(first_seen=ago(200 * DAY), last_in_stock=ago(61 * DAY))]

    assert retired(entries)


# --- retire_missing_days: delisted by every retailer ---------------------------------------------


@pytest.mark.parametrize(
    "missing_for, expected",
    [
        (6 * DAY, False),
        (7 * DAY - HOUR, False),
        (7 * DAY + HOUR, True),
        (8 * DAY, True),
    ],
    ids=["6d", "just-under-7d", "just-over-7d", "8d"],
)
def test_sole_retailer_delisting_retires_only_after_seven_days(missing_for, expected):
    # Recently first seen and recently in stock, so the 60-day rule cannot be what fires.
    entries = [listing(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(missing_for))]

    assert retired(entries) is expected, f"delisted {missing_for / DAY:.2f} days ago"


# --- several retailers: the rule needs every listing retired ------------------------------------------


def two_listings(first, second):
    return [listing(**first), listing(**second)]


@pytest.mark.parametrize(
    "first, second, expected",
    [
        # no stock anywhere for 60 days: one retailer's recent stock keeps the product alive
        (
            dict(first_seen=ago(120 * DAY), last_in_stock=ago(90 * DAY)),
            dict(first_seen=ago(120 * DAY), last_in_stock=ago(5 * DAY)),
            False,
        ),
        (
            dict(first_seen=ago(120 * DAY), last_in_stock=ago(90 * DAY)),
            dict(first_seen=ago(120 * DAY), last_in_stock=ago(70 * DAY)),
            True,
        ),
        # delisted by every retailer for 7 days: one retailer still listing, or delisted only
        # 6 days ago, keeps the product alive
        (
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(8 * DAY)),
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(30 * DAY)),
            True,
        ),
        (
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(30 * DAY)),
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=None),
            False,
        ),
        (
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(30 * DAY)),
            dict(first_seen=ago(20 * DAY), last_in_stock=ago(15 * DAY), missing_since=ago(6 * DAY)),
            False,
        ),
    ],
    ids=[
        "one-has-stock-5d-ago",
        "both-dry-90d-and-70d",
        "both-delisted-8d-and-30d",
        "one-still-listing",
        "one-delisted-only-6d",
    ],
)
def test_a_product_retires_only_when_every_retailer_listing_is_retired(request, first, second, expected):
    entries = two_listings(first, second)

    assert retired(entries) is expected, f"case {request.node.callspec.id}: expected retired={expected}"


def test_a_fresh_active_product_is_not_retired():
    entries = [listing(first_seen=ago(2 * DAY), last_in_stock=ago(1 * DAY))]

    assert lifecycle.is_retired(entries, RETIRE_AFTER, RETIRE_MISSING) is None
