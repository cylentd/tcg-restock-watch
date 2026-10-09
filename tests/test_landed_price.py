"""Shipping in the price verdict (tcgwatch/msrp.py): landed_price, the config read behind verdict(),
and the verdict's decision and label when a retailer is given.

Oracle: config.yaml's shipping block ("free over this subtotal, else a flat fee") and README "Price
sanity" (a listing above msrp * max_price_ratio is INFLATED). The shipping numbers below are fixtures
for these tests, not the real config.yaml values, so the cases hold whatever the store charges.
Expected values are worked by hand in the comments. No network and no real clock.
"""
from pathlib import Path

import pytest

from tcgwatch import msrp

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPING = {
    "target": {"free_over": 35, "flat_fee": 5},
    "tcgplayer": {"free_over": 0, "flat_fee": 4.99},
}


# --- landed_price: the flat fee applies below the free-shipping threshold -------------------------


@pytest.mark.parametrize(
    "price, retailer, expected",
    [
        (20.00, "target", 25.00),     # under 35: 20 + 5
        (34.99, "target", 39.99),     # one cent under 35: still charged 5
        (40.00, "target", 40.00),     # over 35: free
        (20.00, "tcgplayer", 24.99),  # free_over 0 is no threshold, so the flat fee always applies
        (20.00, "unlisted", 20.00),   # no entry for this retailer: no fee
        (20.00, "TARGET", 25.00),     # the retailer name is matched in lower case
    ],
    ids=["under-threshold", "1c-under", "over-threshold", "zero-threshold", "no-entry", "upper-case-name"],
)
def test_landed_price_adds_the_flat_fee_unless_the_threshold_is_cleared(price, retailer, expected):
    assert msrp.landed_price(price, retailer, SHIPPING) == pytest.approx(expected)


def test_a_missing_free_over_means_no_threshold_so_the_fee_applies():
    # 20 + 5 = 25; a missing free_over reads as 0, not as an error.
    assert msrp.landed_price(20.00, "x", {"x": {"flat_fee": 5}}) == pytest.approx(25.00)


def test_a_missing_flat_fee_means_no_fee():
    # free_over 35 is not reached by 20, and a missing flat_fee reads as 0: 20.
    assert msrp.landed_price(20.00, "x", {"x": {"free_over": 35}}) == pytest.approx(20.00)


# --- _shipping_cfg: the shipping block of config.yaml at the repo root -----------------------------


@pytest.fixture
def config_text(monkeypatch):
    """Replaces the config.yaml read and records the path it was asked for."""
    state = {"path": None, "text": "", "error": None}

    def fake_read_text(self, encoding=None, errors=None):
        state["path"] = self
        if state["error"] is not None:
            raise state["error"]
        return state["text"]

    msrp._shipping_cfg.cache_clear()
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    yield state
    msrp._shipping_cfg.cache_clear()


def test_the_shipping_block_is_returned(config_text):
    config_text["text"] = "shipping:\n  target: {free_over: 35, flat_fee: 5}\n"

    assert msrp._shipping_cfg() == {"target": {"free_over": 35, "flat_fee": 5}}


def test_a_config_without_a_shipping_block_gives_an_empty_block(config_text):
    config_text["text"] = "discord_webhook: ''\n"

    assert msrp._shipping_cfg() == {}


def test_an_unreadable_config_gives_an_empty_block(config_text):
    config_text["error"] = OSError("config.yaml is gone")

    assert msrp._shipping_cfg() == {}


def test_the_shipping_block_is_read_from_config_yaml_at_the_repo_root(config_text):
    config_text["text"] = "shipping: {}\n"

    msrp._shipping_cfg()

    assert config_text["path"].name == "config.yaml"
    assert config_text["path"].parent == REPO_ROOT


# --- verdict with a retailer: the decision is made on the landed price ----------------------------


@pytest.fixture
def shipping(monkeypatch):
    monkeypatch.setattr(msrp, "_shipping_cfg", lambda: SHIPPING)


def test_shipping_inside_the_ceiling_is_accepted_and_the_label_shows_the_fee(shipping):
    # 100 + 4.99 = 104.99; 104.99 / 100 = 1.0499, which is within 1.10.
    acceptable, label = msrp.verdict(100.00, 100.00, 1.10, retailer="tcgplayer")

    assert acceptable is True
    assert label == "$100.00 + $4.99 shipping = $104.99 (105% of MSRP)"


def test_shipping_that_pushes_the_landed_price_over_the_ceiling_rejects_it(shipping):
    # The item alone is 100 <= 100 x 1.04, but landed 104.99 > 104.00.
    acceptable, label = msrp.verdict(100.00, 100.00, 1.04, retailer="tcgplayer")

    assert acceptable is False
    assert label == "$100.00 + $4.99 shipping = INFLATED $104.99 vs MSRP $100.00 (105%)"


def test_free_shipping_above_the_threshold_adds_nothing_to_the_label(shipping):
    # 40 clears target's 35 threshold, so landed is 40; 40 / 40 = 1.0.
    acceptable, label = msrp.verdict(40.00, 40.00, 1.10, retailer="target")

    assert acceptable is True
    assert label == "$40.00 = MSRP $40.00"
