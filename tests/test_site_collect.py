"""Status page rows: site.collect groups one product across retailers.

Oracle (README "Status page"): "Products are grouped across retailers, with MSRP, TCGplayer market
price, the premium between them, and each retailer's last-seen price and status." Retailers word the
same product differently, so two listings of one product share a row. The premium is the market price
over MSRP (README "Hot first, stale last": "the market premium over MSRP", "premium is 1.3x or more"),
so a $75.00 market on a $50.00 MSRP is 1.5. The inputs are hand-made Products and a hand-seeded state
file; nothing is fetched. The chase-card EV lookup is stubbed out, because it would read
data/pull_rates.yaml and could price singles from TCGplayer.
"""

import pytest

from tcgwatch import grouping, site as site_mod
from tcgwatch.config import Product
from tcgwatch.state import State
from tests.builders import make_config

ETB = "Pokemon Prismatic Evolutions Elite Trainer Box"
ETB_AT_WALMART = "Prismatic Evolutions Elite Trainer Box (Pokemon TCG)"  # the same product, worded differently


@pytest.fixture(autouse=True)
def no_ev_lookup(monkeypatch):
    monkeypatch.setattr(site_mod.ev, "match_group", lambda name: None)


def collect_page(tmp_path, products, seen, market=None):
    """Seed the state file with each listing's last poll, then build the page data.

    `seen` maps a product key to its saved fields, e.g. {"target:111": {"in_stock": True, "price": 49.99}}.
    `market` maps a product name to its saved TCGplayer market price. The state file keys a market
    price by the product's group key, which is only where the page looks it up, never an expected value.
    """
    state = State(tmp_path / "state.json")
    for key, fields in seen.items():
        state.update(key, **fields)
    for name, price in (market or {}).items():
        state.update(f"market:{grouping.group_key(name)}", market=price)
    return site_mod.collect(make_config(tmp_path, products=products))


@pytest.fixture
def shared_row_page(tmp_path):
    """One ETB listed at Target (in stock, $49.99) and, in other words, at Walmart (sold out)."""
    products = [
        Product("target", "111", ETB, msrp=49.99),
        Product("walmart", "222", ETB_AT_WALMART, msrp=49.99),
    ]
    seen = {"target:111": {"in_stock": True, "price": 49.99}, "walmart:222": {"in_stock": False, "price": None}}
    return collect_page(tmp_path, products, seen)


def test_two_retailers_listing_the_same_product_in_different_words_share_one_row(shared_row_page):
    page = shared_row_page

    assert len(page["groups"]) == 1, f"expected one row, got {[g['name'] for g in page['groups']]}"
    row_listings = {l["retailer"]: (l["status"], l["price"]) for l in page["groups"][0]["listings"]}
    assert row_listings == {"target": ("in", 49.99), "walmart": ("out", None)}


def test_the_shared_row_is_in_stock_when_any_one_retailer_has_it(shared_row_page):
    page = shared_row_page

    assert [g["in_stock"] for g in page["groups"]] == [True], "one row, in stock because Target has it"


def test_different_products_stay_in_separate_rows_even_at_one_retailer_each(tmp_path):
    products = [
        Product("target", "111", ETB, msrp=49.99),
        Product("walmart", "333", "Pokemon Prismatic Evolutions Booster Bundle", msrp=26.94),
    ]

    page = collect_page(tmp_path, products, {})

    assert sorted(len(g["listings"]) for g in page["groups"]) == [1, 1], "an ETB and a Booster Bundle must not share a row"


@pytest.mark.parametrize(
    "msrp, market, premium",
    [
        (50.00, 75.00, 1.5),    # 75.00 / 50.00: market 50% above MSRP
        (50.00, 100.00, 2.0),   # 100.00 / 50.00
        (50.00, 40.00, 0.8),    # 40.00 / 50.00: market below MSRP is a premium under 1
        (50.00, None, None),    # no TCGplayer price yet: no premium
        (None, 75.00, None),    # blank MSRP means unknown (README "Prices"): no premium
    ],
    ids=["1.5x", "2.0x", "below-msrp", "no-market-price", "unknown-msrp"],
)
def test_row_shows_msrp_market_price_and_the_premium_between_them(tmp_path, msrp, market, premium):
    product = Product("target", "111", ETB, msrp=msrp)

    page = collect_page(tmp_path, [product], {}, market={ETB: market})

    [row] = page["groups"]
    assert row["msrp"] == msrp, "MSRP shown on the row"
    assert (row["market"] or {}).get("price") == market, "TCGplayer market price shown on the row"
    assert row["premium"] == premium, f"premium for MSRP {msrp} and market {market}"


def test_a_pokemon_center_row_keeps_pokemon_center_in_its_name(tmp_path):
    # grouping.display_name: the store edition is named "Pokemon Center ..."; the plain game word goes.
    products = [
        Product("target", "111", "Pokemon Mega Evolution Elite Trainer Box", msrp=49.99),
        Product("bestbuy", "222", "Pokemon Center Mega Evolution Elite Trainer Box", msrp=59.99),
    ]

    page = collect_page(tmp_path, products, {})

    assert sorted(g["name"] for g in page["groups"]) == ["Mega Evolution Elite Trainer Box",
                                                         "Pokemon Center Mega Evolution Elite Trainer Box"]
