"""Day and second boundaries in tcgwatch/lifecycle.py.

Oracle: README "Hot first, stale last" and config.yaml's retire rules (retire_after_days 60,
retire_missing_days 7), plus the README's "last 7 days" recency rule and "this week" mention window.
The README does not say whether exactly 7 or 60 days counts, so each case sits one second either
side of the limit and no case sits on it. Hand-worked values are in the comments. Time is the
conftest `clock` (NOW is its frozen instant); nothing reads the real clock.
"""
import pytest

from tcgwatch import lifecycle
from tests.conftest import CLOCK_START

NOW = CLOCK_START
DAY = 86_400
SECOND = 1
RETIRE_AFTER = 60
RETIRE_MISSING = 7

BOOSTER_BUNDLE = "Pokemon Prismatic Evolutions Booster Bundle"
RESTOCK_TITLE = "[Target] Prismatic Evolutions ETB back in stock $49.99"
TIN = "Pokemon 30th Celebration Tin"


# --- buzz: the mention window is 7 days -----------------------------------------------------------


@pytest.mark.parametrize(
    "age_s, counted",
    [(7 * DAY - SECOND, True), (7 * DAY + SECOND, False)],
    ids=["1s-inside-7d", "1s-outside-7d"],
)
def test_mention_window_is_seven_days_to_the_second(age_s, counted):
    titles = [(NOW - age_s, RESTOCK_TITLE)]

    assert (lifecycle.buzz(BOOSTER_BUNDLE, titles) == 1) is counted, f"posted {age_s} s ago"


# --- hot_score: the in-stock recency boost lasts 7 days -------------------------------------------


@pytest.mark.parametrize(
    "age_s, expected",
    [
        (7 * DAY - SECOND, 1.8),  # 1.5 x 0.8 (tin) x 1.5 (proven premium, in the last 7 days)
        (7 * DAY + SECOND, 1.2),  # 1.5 x 0.8 (tin), no boost
    ],
    ids=["1s-inside-7d", "1s-outside-7d"],
)
def test_recency_boost_ends_one_second_past_seven_days(age_s, expected):
    assert lifecycle.hot_score(1.5, 0, NOW - age_s, False, TIN) == pytest.approx(expected)


# --- is_retired: delisted by every retailer for 7 days --------------------------------------------


@pytest.mark.parametrize(
    "missing_s, retired",
    [(7 * DAY - SECOND, False), (7 * DAY + SECOND, True)],
    ids=["1s-inside-7d", "1s-outside-7d"],
)
def test_delisting_retires_one_second_past_seven_days(missing_s, retired):
    # First seen 20 days ago, last in stock 15 days ago: the 60-day rule cannot be what fires.
    entries = [{"first_seen": NOW - 20 * DAY, "last_in_stock": NOW - 15 * DAY, "missing_since": NOW - missing_s}]

    assert (lifecycle.is_retired(entries, RETIRE_AFTER, RETIRE_MISSING) is not None) is retired


# --- is_retired: no stock anywhere for 60 days since first seen -----------------------------------


@pytest.mark.parametrize(
    "first_seen_age_s, retired",
    [(60 * DAY - SECOND, False), (60 * DAY + SECOND, True)],
    ids=["1s-inside-60d", "1s-outside-60d"],
)
def test_never_in_stock_retires_one_second_past_sixty_days(first_seen_age_s, retired):
    entries = [{"first_seen": NOW - first_seen_age_s, "last_in_stock": None, "missing_since": None}]

    assert (lifecycle.is_retired(entries, RETIRE_AFTER, RETIRE_MISSING) is not None) is retired


def test_retire_after_one_day_retires_a_product_unseen_for_two_days():
    # retire_after_days 1: two days with no stock is past the limit; the reason counts whole days.
    entries = [{"first_seen": NOW - 2 * DAY, "last_in_stock": None, "missing_since": None}]

    assert lifecycle.is_retired(entries, 1, RETIRE_MISSING) == "no stock anywhere for 2 days"


def test_retire_reason_counts_whole_days_since_the_last_stock_or_first_seen():
    # 61.5 days since first seen with no stock: the reason rounds down to 61 whole days.
    entries = [{"first_seen": NOW - (61 * DAY + DAY // 2), "last_in_stock": None, "missing_since": None}]

    assert lifecycle.is_retired(entries, RETIRE_AFTER, RETIRE_MISSING) == "no stock anywhere for 61 days"


# --- product_kind and type_weight: no name is an unknown product -----------------------------------


def test_a_missing_name_is_kind_other_with_the_default_weight():
    assert lifecycle.product_kind(None) == "Other"
    assert lifecycle.type_weight(None) == 1.0
