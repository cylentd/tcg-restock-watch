"""Unit tests for the price verdict (tcgwatch/msrp.py), judged against README "Price sanity".

Oracle: "A listing above msrp * max_price_ratio (default 1.10) still alerts but is labeled
INFLATED". So at exactly 1.10x the listing is still fine, one cent over is INFLATED, and a
blank MSRP means unknown. Expected values are worked by hand below. No retailer is passed to
verdict(), so the shipping block of config.yaml is never read.
"""

from __future__ import annotations

import pytest

from tcgwatch import config as config_mod
from tcgwatch import msrp

RATIO = 1.10


@pytest.mark.parametrize(
    "price, msrp_value, acceptable",
    [
        # msrp 100 x 1.10 = 110.00 is the ceiling.
        (100.00, 100.00, True),
        (109.99, 100.00, True),
        (110.00, 100.00, True),   # exactly 1.10x: not "above", so still fine
        (110.01, 100.00, False),  # one cent over
        (150.00, 100.00, False),
        (80.00, 100.00, True),    # under MSRP
        # Pokemon ETB at its README MSRP $49.99: 49.99 x 1.10 = 54.989, so $54.98 passes, $54.99 does not.
        (54.98, 49.99, True),
        (54.99, 49.99, False),
    ],
)
def test_verdict_accepts_up_to_1_10x_msrp_and_rejects_above(price, msrp_value, acceptable):
    got, label = msrp.verdict(price, msrp_value, RATIO)

    assert got is acceptable, f"price {price} vs MSRP {msrp_value} at ratio {RATIO}: label {label!r}"


@pytest.mark.parametrize("price, msrp_value", [(110.01, 100.00), (54.99, 49.99), (349.00, 161.64)])
def test_over_ceiling_label_says_inflated_and_shows_the_price(price, msrp_value):
    _, label = msrp.verdict(price, msrp_value, RATIO)

    assert "INFLATED" in label
    assert f"${price:.2f}" in label
    assert f"${msrp_value:.2f}" in label


@pytest.mark.parametrize("price", [100.00, 109.99, 110.00, 49.00])
def test_at_or_under_ceiling_label_is_not_inflated(price):
    _, label = msrp.verdict(price, 100.00, RATIO)

    assert "INFLATED" not in label


def test_blank_msrp_is_unknown_so_never_inflated():
    acceptable, label = msrp.verdict(300.00, None, RATIO)

    assert acceptable is True
    assert "INFLATED" not in label
    assert "no MSRP" in label
    assert "$300.00" in label


def test_unknown_price_is_acceptable_and_says_so():
    acceptable, label = msrp.verdict(None, 49.99, RATIO)

    assert acceptable is True
    assert label == "price unknown"


@pytest.mark.parametrize(
    "price, max_ratio, acceptable",
    [
        (100.00, 1.00, True),    # strict ratio: at MSRP passes
        (100.01, 1.00, False),   # strict ratio: one cent over fails
        (125.00, 1.25, True),    # loose ratio: exactly 1.25x passes
        (125.01, 1.25, False),
        (120.00, 1.10, False),   # the default ratio would reject what 1.25 allows
    ],
)
def test_ceiling_follows_the_configured_ratio(price, max_ratio, acceptable):
    got, label = msrp.verdict(price, 100.00, max_ratio)

    assert got is acceptable, f"ratio {max_ratio}: label {label!r}"


def test_default_max_price_ratio_is_1_10(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(f"data_dir: {tmp_path.as_posix()}/data\nproducts: []\n", encoding="utf-8")

    cfg = config_mod.load(cfg_file)

    assert cfg.max_price_ratio == 1.10


def test_config_ratio_override_is_read(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(f"data_dir: {tmp_path.as_posix()}/data\nmax_price_ratio: 1.25\nproducts: []\n", encoding="utf-8")

    cfg = config_mod.load(cfg_file)

    assert cfg.max_price_ratio == 1.25


def test_blank_msrp_in_config_loads_as_unknown(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"data_dir: {tmp_path.as_posix()}/data\n"
        "products:\n"
        "  - {retailer: target, id: '1', name: With MSRP, msrp: 49.99}\n"
        "  - {retailer: target, id: '2', name: Blank MSRP}\n",
        encoding="utf-8",
    )

    cfg = config_mod.load(cfg_file)

    assert [p.msrp for p in cfg.products] == [49.99, None]


# README "Prices": the manufacturer list prices the reference table is built from.
@pytest.mark.parametrize(
    "game, kind, expected",
    [
        ("pokemon", "booster_pack", 4.49),
        ("pokemon", "elite_trainer_box", 49.99),
        ("pokemon", "ultra_premium_collection", 119.99),
        ("onepiece", "starter_deck", 11.99),
        ("onepiece", "booster_pack", 4.99),
    ],
)
def test_reference_msrp_matches_readme_list_price(game, kind, expected):
    assert msrp.MSRP[game][kind] == expected
