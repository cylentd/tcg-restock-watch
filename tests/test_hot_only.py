"""Hot-only wiring: products that are not hot are neither polled nor shown on the page.

Oracle (README "Hot items"): "Only hot items are worth tracking; loose packs are not." A booster
bundle and an Elite Trainer Box are hot; a tin is not (the not-hot types win). The rule itself is
tested in test_hotlist.py; here the watcher's poll list, its TCGplayer market tick and the status
page rows must all drop the tin and keep the hot products. Nothing is fetched: the retailer checker
and the market search are recorded stand-ins, and the page data is built from hand-made Products.
"""

import pytest

from tcgwatch import site as site_mod
from tcgwatch import watcher as watcher_mod
from tcgwatch.config import Product
from tests.builders import make_config, make_watcher

HOT_ETB = Product("target", "1", "Pokemon Prismatic Evolutions Elite Trainer Box", msrp=49.99)
HOT_BUNDLE = Product("target", "2", "Pokemon Booster Bundle Beta", msrp=26.94)
NOT_HOT_TIN = Product("target", "3", "Pokemon Old Set Tin", msrp=24.99)


@pytest.fixture(autouse=True)
def no_ev_lookup(monkeypatch):
    monkeypatch.setattr(site_mod.ev, "match_group", lambda name: None)


def test_watcher_polls_the_hot_products_and_skips_the_tin(tmp_path):
    w = make_watcher(tmp_path, products=[HOT_ETB, NOT_HOT_TIN, HOT_BUNDLE])

    polled = w.active_products("target")

    assert polled == [HOT_ETB, HOT_BUNDLE]


def test_the_retailer_check_is_handed_only_hot_products(tmp_path, monkeypatch):
    w = make_watcher(tmp_path, products=[HOT_ETB, NOT_HOT_TIN])
    handed = []

    def checker(products, cfg, browser):
        handed.extend(products)
        return []

    monkeypatch.setattr(watcher_mod, "get_checker", lambda retailer: checker)

    w.run_retailer("target")

    assert handed == [HOT_ETB]


def test_the_market_tick_never_prices_a_product_that_is_not_hot(tmp_path, monkeypatch):
    w = make_watcher(tmp_path, products=[NOT_HOT_TIN, HOT_ETB])
    queried = []

    def fake_search(query, game, pin=None):
        queried.append(query)
        return {"market": 12.5, "name": "x", "product_id": 1}

    monkeypatch.setattr(watcher_mod.market_mod, "search", fake_search)

    for _ in range(2):  # two ticks: the tin would be the second product priced if it were not skipped
        w.run_market_tick()

    assert len(queried) == 1
    assert "Tin" not in queried[0]
    assert "Elite Trainer" in queried[0]


def test_the_page_has_a_row_for_each_hot_product_and_none_for_the_tin(tmp_path):
    cfg = make_config(tmp_path, products=[HOT_ETB, NOT_HOT_TIN, HOT_BUNDLE])

    page = site_mod.collect(cfg)

    names = sorted(g["name"] for g in page["groups"])
    assert len(names) == 2
    assert not any("Tin" in n for n in names), names
