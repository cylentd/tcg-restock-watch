"""Unit tests for tcgwatch/site_data/trends.py, judged against docs/trends.md (the oracle).

The provider turns the page's (hot) groups plus price_history.jsonl into the `trends` page data. The
clock is the frozen 2027-01-15 (tests/conftest.py); every expected value is worked by hand in a comment.
"""

from __future__ import annotations

import pytest

from tcgwatch import history
from tcgwatch import trends as rules
from tcgwatch.site_data import trends as provider
from tests.builders import make_config

POKEMON = "Pokemon|prismatic evolutions elite trainer box"
ONE_PIECE = "One Piece|op 09 booster box"


def group(key=POKEMON, game="Pokemon", name="Prismatic Evolutions Elite Trainer Box", msrp=49.99, market=None):
    return {"key": key, "game": game, "name": name, "msrp": msrp,
            "market": {"price": market} if market is not None else None, "listings": []}


def record(tmp_path, key, prices):
    for day, price in prices.items():
        history.record(tmp_path, key, price, on=day)


def games(tmp_path, groups, **cfg):
    return provider.provide(make_config(tmp_path, **cfg), None, groups)["trends"]["games"]


def products(tmp_path, groups, **cfg):
    return provider.provide(make_config(tmp_path, **cfg), None, groups)["trends"]["products"]


# --- per-game series ----------------------------------------------------------------------

def test_game_series_is_the_index_with_latest_and_a_peak_flag(tmp_path):
    # Window is 2026-10-17..2027-01-15. Base 12-16 (29 days before the last point = ok, >= 28).
    # 12-16: 20 -> 100.0; 01-14: 24 / 20 = 1.2 -> 120.0. Latest 120.0 is the max, so at the peak.
    record(tmp_path, POKEMON, {"2026-12-16": 20.0, "2027-01-14": 24.0})

    got = games(tmp_path, [group()])["Pokemon"]

    assert got["index"] == [["2026-12-16", 100.0], ["2027-01-14", 120.0]]
    assert (got["latest"], got["at_peak"], got["early"], got["status"]) == (120.0, True, False, "ok")


def test_a_latest_point_more_than_5_percent_under_the_peak_is_not_at_the_peak(tmp_path):
    # 12-16: 20 -> 100; 12-30: 30 -> 150; 01-14: 24 -> 120. Max 150, floor 142.5: 120 is under it.
    record(tmp_path, POKEMON, {"2026-12-16": 20.0, "2026-12-30": 30.0, "2027-01-14": 24.0})

    got = games(tmp_path, [group()])["Pokemon"]

    assert (got["latest"], got["at_peak"]) == (120.0, False)


def test_a_game_under_its_high_reports_how_far_under_in_percent(tmp_path):
    # 12-16: 20 -> 100; 12-30: 30 -> 150; 01-14: 24 -> 120. High 150, latest 120: (150 - 120) / 150 = 20%.
    record(tmp_path, POKEMON, {"2026-12-16": 20.0, "2026-12-30": 30.0, "2027-01-14": 24.0})

    got = games(tmp_path, [group()])["Pokemon"]

    assert got["below_high"] == 20.0


def test_a_game_at_its_peak_but_not_at_the_high_reports_the_small_drop(tmp_path):
    # 12-16: 20 -> 100; 12-30: 40 -> 200; 01-14: 39.4 / 20 = 1.97 -> 197.0. Floor 190, so at the peak,
    # yet 3 points under the high of 200: 3 / 200 = 1.5% (the card must not read as a plain "peak").
    record(tmp_path, POKEMON, {"2026-12-16": 20.0, "2026-12-30": 40.0, "2027-01-14": 39.4})

    got = games(tmp_path, [group()])["Pokemon"]

    assert (got["at_peak"], got["latest"], got["below_high"]) == (True, 197.0, 1.5)


def test_a_game_at_its_high_is_zero_under_it(tmp_path):
    record(tmp_path, POKEMON, {"2026-12-16": 20.0, "2027-01-14": 24.0})

    assert games(tmp_path, [group()])["Pokemon"]["below_high"] == 0.0


def test_below_high_is_rounded_to_one_digit(tmp_path):
    # 12-16: 30 -> 100; 12-30: 90 -> 300; 01-14: 40 -> 133.3. (300 - 133.3) / 300 = 55.5666...% -> 55.6.
    record(tmp_path, POKEMON, {"2026-12-16": 30.0, "2026-12-30": 90.0, "2027-01-14": 40.0})

    assert games(tmp_path, [group()])["Pokemon"]["below_high"] == 55.6


@pytest.mark.parametrize("prices", [{}, {"2027-01-10": 50.0, "2027-01-14": 55.0}], ids=["no-data", "early-data"])
def test_without_enough_history_there_is_no_distance_from_the_high(tmp_path, prices):
    record(tmp_path, POKEMON, prices)

    assert games(tmp_path, [group()])["Pokemon"]["below_high"] is None


def test_under_28_days_of_history_flags_early_data_and_never_a_peak(tmp_path):
    # 5 days of history. 01-10: 50 -> 100; 01-14: 55 / 50 = 1.1 -> 110.0.
    record(tmp_path, ONE_PIECE, {"2027-01-10": 50.0, "2027-01-14": 55.0})

    got = games(tmp_path, [group(ONE_PIECE, "One Piece", "OP-09 Booster Box")])["One Piece"]

    assert (got["early"], got["at_peak"], got["latest"], got["status"]) == (True, False, 110.0, "early data")


def test_a_game_with_no_history_has_an_empty_series_and_no_latest(tmp_path):
    got = games(tmp_path, [group()])["Pokemon"]

    assert got == {"status": "no data", "early": False, "index": [], "latest": None, "at_peak": False,
                   "below_high": None}


def test_the_index_of_a_game_takes_the_median_across_its_products(tmp_path):
    # Two Pokemon products. A: 10 -> 15 (1.5), B: 20 -> 25 (1.25). Median of two = mean = 1.375 -> 137.5.
    other = "Pokemon|other box"
    record(tmp_path, POKEMON, {"2026-12-16": 10.0, "2027-01-14": 15.0})
    record(tmp_path, other, {"2026-12-16": 20.0, "2027-01-14": 25.0})

    got = games(tmp_path, [group(), group(other, name="Other Box")])["Pokemon"]

    assert got["latest"] == 137.5


def test_no_groups_gives_empty_trends(tmp_path):
    assert provider.provide(make_config(tmp_path), None, []) == {"trends": {"games": {}, "products": {}}}


# --- per-product bands and drop risk ------------------------------------------------------

def test_a_product_gets_its_deal_and_fair_ceilings(tmp_path):
    # README "Price sanity": deal = MSRP 49.99 x 1.10 = 54.989; fair = market 80 x 0.90 = 72.0.
    got = products(tmp_path, [group(market=80.0)])[POKEMON]

    assert got["deal_below"] == pytest.approx(54.989)
    assert got["fair_below"] == pytest.approx(72.0)
    assert got["drop_risk"] is None


def test_ceilings_keep_three_digits_so_54_99_is_not_a_deal_but_54_98_is(tmp_path):
    # docs/trends.md "Deal bands": MSRP 49.99 x 1.10 = 54.989. Rounded to cents that would be 54.99 and
    # make a $54.99 shelf price a deal; it is not (README "Price sanity"). 54.98 is, 54.99 is fair.
    got = products(tmp_path, [group(market=80.0)])[POKEMON]

    assert got["deal_below"] == 54.989
    assert got["fair_below"] == 72.0
    assert rules.price_band(54.98, got) == "deal"
    assert rules.price_band(54.99, got) == "fair"
    assert rules.price_band(72.01, got) == "high"


def test_a_ceiling_is_rounded_to_three_digits(tmp_path):
    # MSRP 33.3333 x 1.10 = 36.66663 -> 36.667 (not 36.6666); market 66.6666 x 0.90 = 59.99994 -> 60.0.
    got = products(tmp_path, [group(msrp=33.3333, market=66.6666)])[POKEMON]

    assert (got["deal_below"], got["fair_below"]) == (36.667, 60.0)


def test_a_product_carries_what_the_page_prints_about_its_ceilings(tmp_path):
    got = products(tmp_path, [group(market=80.0)])[POKEMON]

    # Shown to the cent, rounded down (docs/trends.md "Deal bands"): 54.989 -> 54.98.
    assert (got["deal_shown"], got["fair_shown"]) == (54.98, 72.0)
    assert (got["fair_line"], got["high_band"], got["high_shown"]) == (True, "fair", 72.0)


def test_a_product_without_msrp_or_market_has_nothing_to_show(tmp_path):
    got = products(tmp_path, [group(msrp=None)])[POKEMON]

    assert (got["deal_shown"], got["fair_shown"], got["fair_line"], got["high_band"], got["high_shown"]) == (
        None, None, False, None, None)


def test_the_deal_ceiling_uses_the_configured_price_ratio(tmp_path):
    # MSRP 50 x 1.2 = 60.
    got = products(tmp_path, [group(msrp=50.0)], max_price_ratio=1.2)[POKEMON]

    assert got["deal_below"] == pytest.approx(60.0)


def test_unknown_msrp_and_market_leave_both_ceilings_none(tmp_path):
    got = products(tmp_path, [group(msrp=None)])[POKEMON]

    assert (got["deal_below"], got["fair_below"]) == (None, None)


def test_an_upcoming_reprint_of_the_products_set_is_its_drop_risk(tmp_path):
    # Frozen today 2027-01-15; the reprint on 2027-02-01 is upcoming and its name is in the product name.
    reprint = {"game": "Pokemon", "name": "Delta Reign", "date": "2027-02-01", "kind": "reprint"}

    got = products(tmp_path, [group(name="Delta Reign Booster Bundle")], releases=[reprint])[POKEMON]

    assert got["drop_risk"] == {"release": "Delta Reign", "date": "2027-02-01"}


def test_a_release_without_kind_reprint_is_no_drop_risk(tmp_path):
    plain = {"game": "Pokemon", "name": "Delta Reign", "date": "2027-02-01"}

    got = products(tmp_path, [group(name="Delta Reign Booster Bundle")], releases=[plain])[POKEMON]

    assert got["drop_risk"] is None


# --- the contract: a missing field fails the build ----------------------------------------

@pytest.mark.parametrize("field", ["game", "name", "msrp", "market"])
def test_a_group_missing_a_field_fails_the_build_and_names_it(tmp_path, field):
    bad = group()
    del bad[field]

    with pytest.raises(ValueError, match=f"trends: group {POKEMON!r} is missing '{field}'"):
        provider.provide(make_config(tmp_path), None, [bad])


def test_a_group_with_no_key_fails_the_build(tmp_path):
    bad = group()
    del bad["key"]

    with pytest.raises(ValueError, match="trends: group .* is missing 'key'"):
        provider.provide(make_config(tmp_path), None, [bad])


def test_a_game_trend_missing_a_field_fails_the_build_and_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "game_trend", lambda series, today: {"status": "ok", "index": []})

    with pytest.raises(ValueError, match="trends: game 'Pokemon' is missing 'peak'"):
        provider.provide(make_config(tmp_path), None, [group()])
