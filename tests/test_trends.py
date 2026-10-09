"""Unit tests for tcgwatch/trends.py, judged against docs/trends.md (the oracle).

Time is injected as `today`; nothing reads the clock or the network. Every expected value is
worked by hand in a comment.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from tcgwatch import history, trends

FIXTURE = Path(__file__).parent / "fixtures" / "price_history_sample.jsonl"
TODAY = date(2026, 9, 29)


def _series(base: str, prices: dict[int, float]) -> list[tuple[str, float]]:
    """{day offset from `base`: price} -> history-style (date, price) list."""
    start = date.fromisoformat(base)
    return [(date.fromordinal(start.toordinal() + off).isoformat(), p) for off, p in sorted(prices.items())]


def _sample_series(tmp_path) -> dict[str, list[tuple[str, float]]]:
    shutil.copy(FIXTURE, tmp_path / history.FILENAME)
    return {k: history.series_for(tmp_path, k) for k in history.read_all(tmp_path)}


# --- game index -------------------------------------------------------------------------

def test_index_is_100_times_median_of_price_ratios_from_the_base_date(tmp_path):
    got = trends.game_trend({k: v for k, v in _sample_series(tmp_path).items() if k.startswith("pokemon")}, TODAY)

    # base 09-01: A 10, B 20 -> 100.
    # 09-15: A 12/10 = 1.2, B 20/20 = 1.0 -> median (two values) 1.1 -> 110.0
    # 09-29: A 15/10 = 1.5, B 25/20 = 1.25 -> median 1.375 -> 137.5
    assert got["index"] == [("2026-09-01", 100.0), ("2026-09-15", 110.0), ("2026-09-29", 137.5)]
    assert got["base_date"] == "2026-09-01"


def test_median_of_three_ignores_the_outlier():
    series = {
        "a": _series("2026-09-01", {0: 10, 28: 10}),   # ratio 1.0
        "b": _series("2026-09-01", {0: 10, 28: 12}),   # ratio 1.2
        "c": _series("2026-09-01", {0: 10, 28: 40}),   # ratio 4.0, the outlier
    }

    got = trends.game_trend(series, TODAY)

    # sorted ratios 1.0, 1.2, 4.0 -> median 1.2 -> 120.0 (a mean would give 220.0)
    assert got["index"][-1] == ("2026-09-29", 120.0)


def test_product_without_a_price_on_the_base_date_is_left_out():
    series = {
        "a": _series("2026-09-01", {0: 10, 28: 20}),   # ratio 2.0 on the last day
        "late": _series("2026-09-01", {10: 5, 28: 5}),  # no 09-01 price: excluded
    }

    got = trends.game_trend(series, TODAY)

    # only A counts: 20/10 = 2.0 -> 200.0; with "late" included the median would be 1.5 -> 150.0
    assert got["index"][-1] == ("2026-09-29", 200.0)


def test_window_drops_points_older_than_90_days():
    today = date(2026, 10, 9)  # window starts 2026-07-11 (90 days back)
    series = {"a": _series("2026-07-10", {0: 100, 1: 10, 91: 20})}  # 07-10 is out; 07-11 is the base

    got = trends.game_trend(series, today)

    # base 07-11 price 10; 10-09 price 20 -> 2.0 -> 200.0. Using 07-10 as base would give 20.0.
    assert got["base_date"] == "2026-07-11"
    assert got["index"][-1] == ("2026-10-09", 200.0)


def test_no_history_says_no_data():
    got = trends.game_trend({}, TODAY)

    assert got["status"] == "no data"
    assert got["index"] == []
    assert got["peak"] is None


# --- early data -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "span_days, status",
    [
        (27, "early data"),  # 09-01 .. 09-28: 27 days, under 28
        (28, "ok"),          # 09-01 .. 09-29: exactly 28 days
    ],
)
def test_under_28_days_of_history_is_early_data(span_days, status):
    series = {"a": _series("2026-09-01", {0: 10, span_days: 11})}

    got = trends.game_trend(series, TODAY)

    assert got["status"] == status
    assert got["history_days"] == span_days


def test_early_data_has_no_peak(tmp_path):
    games = {"pokemon-a": "Pokemon", "pokemon-b": "Pokemon", "onepiece-c": "One Piece"}

    got = trends.trends_by_game(_sample_series(tmp_path), games, TODAY)

    # One Piece: 09-20 .. 09-25 = 5 days of history -> early data. Pokemon: 28 days -> ok.
    assert got["One Piece"]["status"] == "early data"
    assert got["One Piece"]["peak"] is None
    assert got["Pokemon"]["status"] == "ok"
    assert got["Pokemon"]["history_days"] == 28


def test_keys_without_a_game_are_skipped(tmp_path):
    got = trends.trends_by_game(_sample_series(tmp_path), {"pokemon-a": "Pokemon"}, TODAY)

    assert list(got) == ["Pokemon"]


# --- peak -------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "values, peak_date, peak_index, at_peak",
    [
        # max 150, band floor 150 - 7.5 = 142.5. 145 qualifies and is the latest -> not the last day.
        ([100, 150, 145, 120], 2, 145.0, False),
        # last day is the max itself.
        ([100, 120, 150], 2, 150.0, True),
        # max 200, floor 190.0: exactly 190 is inside the band, 189.9 is not.
        ([100, 200, 190], 2, 190.0, True),
        ([100, 200, 189.9], 1, 200.0, False),
    ],
)
def test_peak_is_the_latest_index_within_5_percent_of_the_max(values, peak_date, peak_index, at_peak):
    index = [(f"2026-09-{d + 1:02d}", v) for d, v in enumerate(values)]

    got = trends.peak_of(index)

    assert got["date"] == index[peak_date][0]
    assert got["index"] == peak_index
    assert got["at_peak"] is at_peak


def test_peak_of_nothing_is_none():
    assert trends.peak_of([]) is None


def test_game_trend_reports_the_peak(tmp_path):
    got = trends.game_trend({k: v for k, v in _sample_series(tmp_path).items() if k.startswith("pokemon")}, TODAY)

    # index 100, 110, 137.5: max 137.5, floor 137.5 - 6.875 = 130.625 -> only 09-29 qualifies.
    assert got["peak"] == {"date": "2026-09-29", "index": 137.5, "max": 137.5, "at_peak": True}


# --- deal bands -------------------------------------------------------------------------

def test_bands_are_msrp_x_1_10_and_market_x_0_90():
    got = trends.deal_bands(msrp=100.0, market=50.0)

    # 100 x 1.10 = 110.0 (float 110.00000000000001); 50 x 0.90 = 45.0
    assert got["deal_below"] == pytest.approx(110.0)
    assert got["fair_below"] == pytest.approx(45.0)


def test_unknown_msrp_or_market_gives_no_band():
    assert trends.deal_bands(msrp=None, market=None) == {"deal_below": None, "fair_below": None}


def test_deal_ratio_is_the_configured_max_price_ratio():
    got = trends.deal_bands(msrp=100.0, market=None, deal_ratio=1.25)

    assert got["deal_below"] == pytest.approx(125.0)


@pytest.mark.parametrize(
    "price, expected",
    [
        # msrp 49.99 x 1.10 = 54.989 (README: $54.98 passes, $54.99 does not); market 80 x 0.90 = 72.0
        (54.98, "deal"),
        (54.99, "fair"),    # above the deal ceiling, under 72.0
        (72.00, "fair"),    # exactly the fair ceiling
        (72.01, "high"),
        (40.00, "deal"),
    ],
)
def test_price_band(price, expected):
    bands = trends.deal_bands(msrp=49.99, market=80.0)

    assert trends.price_band(price, bands) == expected


def test_price_band_without_any_reference_is_high():
    assert trends.price_band(10.0, trends.deal_bands(None, None)) == "high"


@pytest.mark.parametrize(
    "msrp, market, price",
    [
        (100.0, 200.0, 100.0),  # deal_below 110, fair_below 180: 100 is under both, deal wins
        (100.0, 50.0, 44.0),    # deal_below 110, fair_below 45: 44 is under both, deal wins
        (100.0, 100.0, 90.0),   # deal_below 110, fair_below 90: exactly on both, deal wins
    ],
)
def test_a_price_under_both_ceilings_is_a_deal_because_deal_is_checked_first(msrp, market, price):
    assert trends.price_band(price, trends.deal_bands(msrp, market)) == "deal"


@pytest.mark.parametrize("fair_below", [None, 80.0], ids=["no-fair-ceiling", "fair-ceiling-above"])
def test_a_price_exactly_on_the_deal_ceiling_is_a_deal(fair_below):
    assert trends.price_band(50.0, {"deal_below": 50.0, "fair_below": fair_below}) == "deal"


def test_a_price_over_the_deal_ceiling_with_no_market_is_high():
    assert trends.price_band(60.0, trends.deal_bands(msrp=49.99, market=None)) == "high"


@pytest.mark.parametrize(
    "ceiling, shown",
    [
        (54.989, 54.98),    # rounds down, so the shown $54.98 still gets the "deal" verdict (README "Price sanity")
        (72.0, 72.0),
        (4.999, 4.99),
        (0.29, 0.29),       # 0.29 x 100 is 28.999999999999996 in binary floats; the shown cent must stay 29
        (110.00000000000001, 110.0),
    ],
)
def test_a_ceiling_is_shown_rounded_down_to_the_cent(ceiling, shown):
    assert trends.shown_ceiling(ceiling) == shown


@pytest.mark.parametrize(
    "bands, expected",
    [
        # MSRP 49.99 x 1.10 = 54.989, market 80 x 0.90 = 72.0: two lines; a high price is over the fair ceiling.
        ({"deal_below": 54.989, "fair_below": 72.0},
         {"deal_shown": 54.98, "fair_shown": 72.0, "fair_line": True, "high_band": "fair", "high_shown": 72.0}),
        # market 50 x 0.90 = 45.0 is under the deal ceiling: fair never applies, a high price is over the deal ceiling.
        ({"deal_below": 54.989, "fair_below": 45.0},
         {"deal_shown": 54.98, "fair_shown": 45.0, "fair_line": False, "high_band": "deal", "high_shown": 54.98}),
        # Equal ceilings: no separate fair line, and the high price is over the fair ceiling.
        ({"deal_below": 50.0, "fair_below": 50.0},
         {"deal_shown": 50.0, "fair_shown": 50.0, "fair_line": False, "high_band": "fair", "high_shown": 50.0}),
        ({"deal_below": 54.989, "fair_below": None},
         {"deal_shown": 54.98, "fair_shown": None, "fair_line": False, "high_band": "deal", "high_shown": 54.98}),
        ({"deal_below": None, "fair_below": 72.0},
         {"deal_shown": None, "fair_shown": 72.0, "fair_line": True, "high_band": "fair", "high_shown": 72.0}),
        ({"deal_below": None, "fair_below": None},
         {"deal_shown": None, "fair_shown": None, "fair_line": False, "high_band": None, "high_shown": None}),
    ],
    ids=["both", "fair-under-deal", "equal", "deal-only", "fair-only", "neither"],
)
def test_band_display_bakes_what_the_page_shows(bands, expected):
    assert trends.band_display(bands) == expected


# --- drop risk --------------------------------------------------------------------------

RELEASES = [
    {"game": "Pokemon", "name": "30th Celebration", "date": "2026-09-16"},                      # no kind
    {"game": "Pokemon", "name": "Mega Evolution: Delta Reign", "date": "2026-11-06", "kind": "reprint"},
    {"game": "Pokemon", "name": "Surging Sparks", "date": "2026-10-20", "kind": "reprint"},
    {"game": "One Piece", "name": "Surging Sparks", "date": "2026-10-21", "kind": "reprint"},   # other game
    {"game": "Pokemon", "name": "Destined Rivals", "date": "2026-09-01", "kind": "reprint"},     # already out
    {"game": "Pokemon", "name": "Prismatic Evolutions", "date": "2026-09-29", "kind": "new"},    # not a reprint
]


@pytest.mark.parametrize(
    "product, expected",
    [
        # reprint release whose name sits inside the product name, upcoming -> risk
        ("Pokemon Surging Sparks Elite Trainer Box", {"release": "Surging Sparks", "date": "2026-10-20"}),
        # punctuation in the release name does not block the match
        ("Pokemon Mega Evolution Delta Reign Booster Bundle", {"release": "Mega Evolution: Delta Reign", "date": "2026-11-06"}),
        # entry has no kind -> no risk
        ("Pokemon 30th Celebration Elite Trainer Box", None),
        # reprint date 2026-09-01 is before today -> already out, no risk
        ("Pokemon Destined Rivals Elite Trainer Box", None),
        # kind is something other than reprint
        ("Pokemon Prismatic Evolutions Booster Bundle", None),
        # no release names this set
        ("Pokemon Scarlet & Violet Booster Bundle", None),
    ],
)
def test_drop_risk_needs_an_upcoming_reprint_of_the_products_set(product, expected):
    assert trends.drop_risk(product, "Pokemon", RELEASES, TODAY) == expected


def test_drop_risk_release_on_today_still_counts():
    releases = [{"game": "Pokemon", "name": "Surging Sparks", "date": "2026-09-29", "kind": "reprint"}]

    assert trends.drop_risk("Pokemon Surging Sparks ETB", "Pokemon", releases, TODAY) is not None


def test_drop_risk_picks_the_earliest_of_two_reprints():
    releases = [
        {"game": "Pokemon", "name": "Surging Sparks", "date": "2026-12-01", "kind": "reprint"},
        {"game": "Pokemon", "name": "Surging Sparks", "date": "2026-10-20", "kind": "reprint"},
    ]

    got = trends.drop_risk("Pokemon Surging Sparks ETB", "Pokemon", releases, TODAY)

    assert got["date"] == "2026-10-20"


def test_drop_risk_other_games_reprint_is_ignored():
    # The One Piece "Surging Sparks" entry must not flag a Pokemon product.
    releases = [r for r in RELEASES if r["game"] == "One Piece"]

    assert trends.drop_risk("Pokemon Surging Sparks ETB", "Pokemon", releases, TODAY) is None
