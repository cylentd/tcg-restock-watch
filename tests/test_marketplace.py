"""Marketplace sellers read as out of stock, at each retailer's parser.

Oracle (README, the paragraph after "Reddit feeds"): "Target, Best Buy, and Walmart all host
third-party 'marketplace' sellers on the same product pages ... The watcher treats a marketplace
listing as out of stock, so an alert always means the retailer itself is selling at its own price."
README "Prices": "Seen at is the price the retailer itself showed", so a reseller's price is never
recorded for the retailer.

Each test feeds a payload from tests/fixtures/ through the retailer's public check() with a fake
browser, so the parser runs for real and no page is loaded. Every fixture is a hand-built minimal
payload in the real answer's shape, holding only the fields the parser reads; replace each with a
recorded answer when one is captured.
"""

from __future__ import annotations

import pytest

from tcgwatch.config import Product
from tcgwatch.retailers import bestbuy, target, walmart
from tests.builders import FakeBrowser, TargetBrowser, WalmartBrowser, load_fixture, make_config

# -- Walmart: embedded page JSON ------------------------------------------------------------


def read_walmart(tmp_path, fixture):
    product = Product("walmart", "99", "Pokemon ETB", msrp=49.99)
    [result] = walmart.check([product], make_config(tmp_path), WalmartBrowser(load_fixture(fixture)))
    return result


@pytest.mark.parametrize(
    "fixture, expected_in_stock",
    [
        ("walmart_first_party_in_stock.json", True),
        ("walmart_first_party_out_of_stock.json", False),
        ("walmart_marketplace_in_stock.json", False),  # status IN_STOCK, but sold by ScalperCo (EXTERNAL)
    ],
    ids=["walmart-sells-it-in-stock", "walmart-sells-it-sold-out", "marketplace-seller-in-stock"],
)
def test_walmart_page_counts_as_in_stock_only_when_walmart_itself_sells_it(tmp_path, fixture, expected_in_stock):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_walmart(tmp_path, fixture)

    assert result.in_stock is expected_in_stock, f"{fixture}: note {result.note!r}"


def test_walmart_marketplace_sellers_price_is_not_recorded_as_walmarts(tmp_path):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_walmart(tmp_path, "walmart_marketplace_in_stock.json")  # ScalperCo asks $349.00

    assert result.price is None, f"a reseller's price leaked into Walmart's price column: {result.price}"


def test_walmart_selling_it_itself_records_its_own_price(tmp_path):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_walmart(tmp_path, "walmart_first_party_in_stock.json")

    assert result.price == 49.99


# -- Target: redsky stock summary, called through the browser ---------------------------------


@pytest.fixture
def target_cold_start(monkeypatch):
    """No cached price, no captcha pause carried over from another test."""
    monkeypatch.setattr(target, "_details_cache", {})
    monkeypatch.setattr(target, "_challenge_until", 0.0)


def read_target(tmp_path, summary_fixture):
    product = Product("target", "222", "Pokemon ETB", msrp=49.99)
    browser = TargetBrowser(load_fixture(summary_fixture), load_fixture("target_pdp_price.json"))
    [result] = target.check([product], make_config(tmp_path), browser)
    return result


@pytest.mark.parametrize(
    "fixture, expected_in_stock",
    [
        ("target_summary_first_party_in_stock.json", True),
        ("target_summary_first_party_out_of_stock.json", False),
        ("target_summary_marketplace_in_stock.json", False),  # IN_STOCK, but a Target Plus seller (is_marketplace)
    ],
    ids=["target-sells-it-in-stock", "target-sells-it-sold-out", "target-plus-seller-in-stock"],
)
def test_target_summary_counts_as_in_stock_only_when_target_itself_sells_it(
    tmp_path, target_cold_start, fixture, expected_in_stock
):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_target(tmp_path, fixture)

    assert result.in_stock is expected_in_stock, f"{fixture}: note {result.note!r}"


def test_target_plus_sellers_price_is_not_recorded_as_targets(tmp_path, target_cold_start):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_target(tmp_path, "target_summary_marketplace_in_stock.json")

    assert result.price is None, f"a Target Plus seller's price leaked into Target's price column: {result.price}"


def test_target_selling_it_itself_records_its_own_price(tmp_path, target_cold_start):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_target(tmp_path, "target_summary_first_party_in_stock.json")

    assert result.price == 49.99


# -- Best Buy: product page read (no API key); the API lists only Best Buy's own offers ----------


@pytest.fixture
def bestbuy_first_product(monkeypatch):
    """Start the pass at the first product, whatever an earlier test rotated the start to."""
    monkeypatch.setattr(bestbuy, "_start", 0)


def read_bestbuy(tmp_path, page_fixture):
    product = Product("bestbuy", "6600001", "Pokemon ETB", msrp=49.99)
    browser = FakeBrowser(load_fixture(page_fixture))
    [result] = bestbuy.check([product], make_config(tmp_path), browser)
    return result


@pytest.mark.parametrize(
    "fixture, expected_in_stock",
    [
        ("bestbuy_page_first_party_in_stock.json", True),
        ("bestbuy_page_first_party_sold_out.json", False),
        ("bestbuy_page_marketplace_in_stock.json", False),  # add-to-cart enabled, but sold by ScalperCo
    ],
    ids=["best-buy-sells-it-in-stock", "best-buy-sells-it-sold-out", "marketplace-seller-in-stock"],
)
def test_best_buy_page_counts_as_in_stock_only_when_best_buy_itself_sells_it(
    tmp_path, bestbuy_first_product, fixture, expected_in_stock
):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_bestbuy(tmp_path, fixture)

    assert result.in_stock is expected_in_stock, f"{fixture}: note {result.note!r}"


def test_best_buy_marketplace_sellers_price_is_not_recorded_as_best_buys(tmp_path, bestbuy_first_product):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_bestbuy(tmp_path, "bestbuy_page_marketplace_in_stock.json")  # ScalperCo asks $349.00

    assert result.price is None, f"a reseller's price leaked into Best Buy's price column: {result.price}"


def test_best_buy_selling_it_itself_records_its_own_price(tmp_path, bestbuy_first_product):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    result = read_bestbuy(tmp_path, "bestbuy_page_first_party_in_stock.json")

    assert result.price == 49.99


# -- Malformed payloads: unknown (None), never in stock ---------------------------------------
# Oracle (README "Known limits"): "When a check starts returning `None` for every product, the
# endpoint or page shape moved." A payload with the field that decides stock missing therefore reads
# as None (unknown), not False and never True, and records no price. Each fixture is hand-built (its
# "_note" key says so) to look in stock apart from the one missing field.


def test_walmart_page_without_its_initial_data_block_reads_as_unknown(tmp_path):
    """Fixture: hand-built malformed payload (props.pageProps has no initialData)."""
    result = read_walmart(tmp_path, "walmart_malformed_no_initial_data.json")

    assert (result.in_stock, result.price) == (None, None), f"note {result.note!r}"


def test_target_summary_entry_without_a_tcin_reads_as_unknown(tmp_path, target_cold_start):
    """Fixture: hand-built malformed payload (an IN_STOCK entry with no tcin to attach it to)."""
    result = read_target(tmp_path, "target_summary_malformed_no_tcin.json")

    assert (result.in_stock, result.price) == (None, None), f"note {result.note!r}"


def test_best_buy_page_read_without_a_url_reads_as_unknown(tmp_path, bestbuy_first_product):
    """Fixture: hand-built malformed payload (enabled Add to Cart, but no url: the page never loaded)."""
    result = read_bestbuy(tmp_path, "bestbuy_page_malformed_no_url.json")

    assert (result.in_stock, result.price) == (None, None), f"note {result.note!r}"
