"""Pin the mid-pass Chrome recycle in tcgwatch.retailers.bestbuy._browser_check.

A fresh tab per product still lets Chrome's own memory climb past the cap inside a
single Best Buy pass (33 products), because the old recycle check only ran between
passes. These tests fake the browser and its memory reading so no real agent-browser
or Chrome process is needed.
"""

from __future__ import annotations

import pytest

from tcgwatch.config import Product
from tcgwatch.retailers import bestbuy
from tests.builders import FakeBrowser


def _products(n: int) -> list[Product]:
    return [Product(retailer="bestbuy", id=str(1000 + i), name=f"Product {i}") for i in range(n)]


IN_STOCK_PAGE = {
    "url": "https://www.bestbuy.com/site/123.p",
    "hasButton": True,
    "enabled": True,
    "label": "Add to Cart",
    "seller": "Best Buy",
    "price": "19.99",
    "soldOut": False,
    "comingSoon": False,
    "blocked": False,
    "image": "",
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # _browser_check paces itself with time.sleep between products; skip that in tests.
    monkeypatch.setattr(bestbuy.time, "sleep", lambda s: None)
    monkeypatch.setattr(bestbuy.random, "uniform", lambda a, b: 0)


def test_midpass_recycle_fires_after_tab_close_when_over_cap():
    products = _products(3)
    browser = FakeBrowser(IN_STOCK_PAGE, over_cap_after=1)  # over cap right after product 1
    from tcgwatch.config import Config

    cfg = object.__new__(Config)  # cfg is unused by _browser_check itself
    results = bestbuy._browser_check(products, cfg, browser)

    assert len(results) == 3
    assert len(browser.recycle_calls) == 1, f"one recycle after product 1, then under the cap: {browser.recycle_calls}"
    # It checked memory after every tab close, not just once.
    assert browser.calls == 3
    assert browser.tab_closes == 3


def test_midpass_recycle_does_not_fire_when_under_cap():
    products = _products(3)
    browser = FakeBrowser(IN_STOCK_PAGE, over_cap_after=None)  # never over cap
    from tcgwatch.config import Config

    cfg = object.__new__(Config)
    results = bestbuy._browser_check(products, cfg, browser)

    assert len(results) == 3
    assert browser.recycle_calls == []
    assert browser.calls == 3
