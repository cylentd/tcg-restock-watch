"""Walmart check(): the page parse, the captcha stop, the load-error cutoff and the lookup.

Oracle, README where it speaks:
- "Walmart | Loads product page in the background browser, reads embedded JSON, marketplace sellers
  ignored | Needs background browser: Yes": no browser means no answer; a marketplace seller is out of stock.
- "Walmart wants a captcha when the 'Robot or human?' page appears" (Alerts): the note starts with
  "captcha", the exact prefix watcher.py keys the alert on.
- "Known limits": a page shape that moved reads None (unknown), never in stock.
- "Seen at ... Walmart read off the page each check": the price is the page's own price.
Where README is silent the behaviour is pinned from walmart.py's own comments, and each such test
says so in its docstring: image choice, the three-load-error cutoff, the 6 to 12 s pacing, the
1200 ms settle wait, the note wording, the seller rules and the lookup result.

Pages come from tests/fixtures/ (hand-built in the real __NEXT_DATA__ shape) through a scripted fake
browser. Pacing sleeps are replaced so no test waits.
"""

from __future__ import annotations

import re

import pytest

from tcgwatch.config import Product
from tcgwatch.retailers import walmart
from tests.builders import ScriptedWalmartBrowser, WalmartBrowser, load_fixture, make_config

FIRST_PARTY_IN_STOCK = "walmart_first_party_in_stock.json"  # Walmart.com, IN_STOCK, $49.99


def products(*ids: str) -> list[Product]:
    return [Product("walmart", i, f"Pokemon ETB {i}", msrp=49.99) for i in ids]


def url_of(item_id: str) -> str:
    return f"https://www.walmart.com/ip/{item_id}"


def page(fixture: str | None = FIRST_PARTY_IN_STOCK, **extra) -> dict:
    return {"data": load_fixture(fixture) if fixture else None, **extra}


def read_one(tmp_path, fixture: str):
    [result] = walmart.check(products("99"), make_config(tmp_path), WalmartBrowser(load_fixture(fixture)))
    return result


@pytest.fixture(autouse=True)
def pacing(monkeypatch):
    """No real sleep between page loads, in any test of this module; records what check() asked for."""
    log = {"uniform": [], "sleeps": [], "events": []}  # events: ("sleep", s) here, ("open", url) from a browser given it

    def fake_uniform(low, high):
        log["uniform"].append((low, high))
        return 7.5

    def fake_sleep(seconds):
        log["sleeps"].append(seconds)
        log["events"].append(("sleep", seconds))

    monkeypatch.setattr(walmart.random, "uniform", fake_uniform)
    monkeypatch.setattr(walmart.time, "sleep", fake_sleep)
    return log


# -- Nothing to check, or nothing to check with ----------------------------------------------


def test_no_products_returns_an_empty_list(tmp_path):
    assert walmart.check([], make_config(tmp_path), WalmartBrowser({})) == []


def test_without_a_browser_every_product_reads_unknown_browser_required(tmp_path):
    """README: Walmart needs the background browser; no browser means no answer, never in stock."""
    results = walmart.check(products("1", "2"), make_config(tmp_path), None)

    assert [(r.in_stock, r.price, r.url, r.note) for r in results] == [
        (None, None, url_of("1"), "browser required"),
        (None, None, url_of("2"), "browser required"),
    ]


# -- The page parse --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture, expected_image",
    [
        ("walmart_first_party_in_stock_thumbnail_and_gallery.json", "https://img.test/thumb.jpg"),
        ("walmart_first_party_in_stock_gallery_only.json", "https://img.test/gallery-1.jpg"),
        ("walmart_first_party_in_stock_empty_thumbnail_with_gallery.json", "https://img.test/gallery-1.jpg"),
        ("walmart_first_party_in_stock_empty_image_info.json", None),
        (FIRST_PARTY_IN_STOCK, None),  # no imageInfo block at all
    ],
    ids=["thumbnail-wins", "first-gallery-image", "empty-thumbnail-falls-through", "empty-gallery", "no-image-info"],
)
def test_image_is_the_thumbnail_else_the_first_gallery_image_else_none(tmp_path, fixture, expected_image):
    """Pinned from walmart._image: README only says the image is "as shown by the retailer"."""
    assert read_one(tmp_path, fixture).image == expected_image


@pytest.mark.parametrize(
    "fixture, expected_note",
    [
        ("walmart_product_missing_two_errors.json", "product missing (NOT_FOUND)"),  # the first error, not the second
        ("walmart_product_missing_no_errors.json", "product missing (no product)"),
        ("walmart_next_data_props_null.json", "no initialData"),  # props null: reads unknown, no crash
    ],
    ids=["error-names-the-cause", "no-product-no-error", "props-null"],
)
def test_page_without_a_product_reads_unknown_and_says_why(tmp_path, fixture, expected_note):
    """README "Known limits": unknown, not False. The note wording is pinned from walmart._parse."""
    result = read_one(tmp_path, fixture)

    assert (result.in_stock, result.price, result.note) == (None, None, expected_note)


@pytest.mark.parametrize(
    "fixture, expected_in_stock, expected_price",
    [
        ("walmart_internal_seller_other_name_in_stock.json", True, 49.99),  # INTERNAL alone is Walmart
        ("walmart_seller_named_walmart_no_type_in_stock.json", True, 49.99),  # "WALMART.COM": name alone, any case
        ("walmart_seller_named_walmart_lowercase_no_type_in_stock.json", True, 49.99),  # bare "walmart"
        ("walmart_seller_named_walmart_deals_no_type_in_stock.json", False, None),  # "Walmart Deals": whole name must match
        ("walmart_unknown_seller_no_type_in_stock.json", False, None),  # neither: a third party
        ("walmart_external_type_named_walmart_com_in_stock.json", True, 49.99),  # the rule is "or": the name is enough
        ("walmart_internal_type_lowercase_in_stock.json", True, 49.99),  # sellerType "internal", any case
    ],
    ids=[
        "internal-type", "walmart-com-name", "bare-walmart-name", "name-only-contains-walmart", "neither",
        "external-type-walmart-name", "lowercase-internal-type",
    ],
)
def test_walmart_is_the_seller_when_either_its_type_or_its_name_says_so(
    tmp_path, fixture, expected_in_stock, expected_price
):
    """Confirmed by David 2026-10-06: first party is sellerType INTERNAL, or a seller name that is exactly
    walmart or walmart.com in any case ("Walmart Deals" is a marketplace seller)."""
    result = read_one(tmp_path, fixture)

    assert (result.in_stock, result.price) == (expected_in_stock, expected_price)


def test_first_party_note_names_the_status_and_seller(tmp_path):
    """Pinned from walmart._parse: "<STATUS> seller=<name>"."""
    assert read_one(tmp_path, FIRST_PARTY_IN_STOCK).note == "IN_STOCK seller=Walmart.com"


def test_marketplace_note_says_the_listing_was_ignored(tmp_path):
    """README: marketplace sellers ignored. Wording pinned loosely from walmart._parse (ScalperCo asks $349.00)."""
    note = read_one(tmp_path, "walmart_marketplace_in_stock.json").note

    assert "marketplace, ignored" in note
    assert "ScalperCo" in note
    assert re.search(r"\$349(\.0+)?\b", note), note  # the price, whatever float formatting prints


# -- The captcha stop ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tab",
    [
        {"url": None, "title": "Robot or human?"},  # no URL yet: only the title says so
        {"url": "https://www.walmart.com/blocked?url=L2lwLzk5", "title": None},  # no title: only the URL says so
        {"url": url_of("99"), "title": "Robot Or Human?"},  # any letter case
    ],
    ids=["title-only", "url-only", "mixed-case"],
)
def test_robot_or_human_page_reads_unknown_and_flags_a_captcha(tmp_path, tab):
    """README "Alerts": Walmart wants a captcha when the "Robot or human?" page appears."""
    browser = ScriptedWalmartBrowser([page(**tab)])

    [result] = walmart.check(products("99"), make_config(tmp_path), browser)

    assert (result.in_stock, result.price, result.note) == (None, None, "captcha")
    assert result.url == url_of("99")


def test_a_captcha_skips_the_rest_of_the_round_without_loading_them(tmp_path, pacing):
    """Confirmed by David 2026-10-06: one captcha skips the rest of the round, which is never loaded."""
    browser = ScriptedWalmartBrowser([page(), page(title="Robot or human?")])

    results = walmart.check(products("1", "2", "3", "4"), make_config(tmp_path), browser)

    assert [(r.in_stock, r.note, r.url) for r in results] == [
        (True, "IN_STOCK seller=Walmart.com", url_of("1")),
        (None, "captcha", url_of("2")),
        (None, "captcha (skipped)", url_of("3")),
        (None, "captcha (skipped)", url_of("4")),
    ]
    assert browser.opened == [url_of("1"), url_of("2")]
    assert pacing["sleeps"] == [7.5]  # only the pause before page 2; the skipped items cause none


# -- A page with no data, and the load-error cutoff -------------------------------------------


def test_page_without_next_data_reads_unknown_and_the_pass_goes_on(tmp_path, pacing):
    """README "Known limits": unknown. The note wording is pinned from walmart.check."""
    browser = ScriptedWalmartBrowser([page(None), page()])

    results = walmart.check(products("1", "2"), make_config(tmp_path), browser)

    assert [(r.in_stock, r.note) for r in results] == [
        (None, "no __NEXT_DATA__"),
        (True, "IN_STOCK seller=Walmart.com"),
    ]


def test_empty_next_data_object_reads_unknown_with_a_note(tmp_path):
    """Pinned from walmart.check: an empty blob is "no data", not a crash and never in stock."""
    result = read_one(tmp_path, "walmart_next_data_empty_object.json")

    assert (result.in_stock, result.price, result.note) == (None, None, "no __NEXT_DATA__")


def test_load_errors_read_unknown_and_the_fourth_item_is_skipped_after_three(tmp_path, pacing):
    """Confirmed by David 2026-10-06: three failed loads in a row stop the pass, so a broken browser is not hammered."""
    boom = RuntimeError("boom")
    browser = ScriptedWalmartBrowser([page(error=boom)] * 3 + [page()])

    results = walmart.check(products("1", "2", "3", "4"), make_config(tmp_path), browser)

    assert [(r.in_stock, r.note) for r in results] == [
        (None, "browser error: boom"),
        (None, "browser error: boom"),
        (None, "browser error: boom"),
        (None, "skipped after repeated load errors"),
    ]
    assert results[3].url == url_of("4")
    assert browser.opened == [url_of("1"), url_of("2"), url_of("3")]
    assert pacing["sleeps"] == [7.5, 7.5]  # before pages 2 and 3; the skipped 4th causes none


def test_a_page_without_next_data_neither_counts_toward_the_error_stop_nor_resets_it(tmp_path, pacing):
    """Pinned from walmart.check (README silent): the "no __NEXT_DATA__" path skips both `failures += 1` and
    `failures = 0`. Error, error, no-data, error reaches three errors, so the 5th item is skipped; had no-data
    counted, the 4th would be skipped, and had it reset, the 5th would load."""
    boom = RuntimeError("boom")
    browser = ScriptedWalmartBrowser([page(error=boom), page(error=boom), page(None), page(error=boom), page()])

    results = walmart.check(products("1", "2", "3", "4", "5"), make_config(tmp_path), browser)

    assert [r.note for r in results] == [
        "browser error: boom",
        "browser error: boom",
        "no __NEXT_DATA__",
        "browser error: boom",
        "skipped after repeated load errors",
    ]
    assert len(browser.opened) == 4


def test_a_good_load_resets_the_error_count(tmp_path, pacing):
    """Confirmed by David 2026-10-06: only consecutive failures count; error, error, ok, error, error still loads the 6th."""
    boom = RuntimeError("boom")
    browser = ScriptedWalmartBrowser([page(error=boom), page(error=boom), page(), page(error=boom), page(error=boom), page()])

    results = walmart.check(products("1", "2", "3", "4", "5", "6"), make_config(tmp_path), browser)

    assert [r.in_stock for r in results] == [None, None, True, None, None, True]
    assert len(browser.opened) == 6


# -- Pacing and settle wait ------------------------------------------------------------------


def test_second_page_waits_6_to_12_seconds_and_the_first_does_not(tmp_path, pacing):
    """Confirmed by David 2026-10-06: 6 to 12 s between page loads, none before the first."""
    browser = ScriptedWalmartBrowser([page(), page(), page()], events=pacing["events"])

    walmart.check(products("1", "2", "3"), make_config(tmp_path), browser)

    assert pacing["uniform"] == [(6, 12), (6, 12)]
    # 7.5 is what the stub drew. A pause before each page after the first, never after a page.
    assert pacing["events"] == [
        ("open", url_of("1")),
        ("sleep", 7.5),
        ("open", url_of("2")),
        ("sleep", 7.5),
        ("open", url_of("3")),
    ]


def test_each_page_gets_1200_ms_to_settle_before_it_is_read(tmp_path):
    """Pinned from walmart.check: wait(1200) after open()."""
    browser = ScriptedWalmartBrowser([page()])

    walmart.check(products("99"), make_config(tmp_path), browser)

    assert browser.waits == [1200]


# -- lookup ----------------------------------------------------------------------------------


def test_lookup_returns_the_products_name_price_status_and_url(tmp_path):
    """README `--lookup RETAILER ID` confirms an ID; the dict shape is pinned from walmart.lookup."""
    browser = WalmartBrowser(load_fixture("walmart_first_party_in_stock_thumbnail_and_gallery.json"))

    got = walmart.lookup(make_config(tmp_path), "99", browser)

    assert got == {
        "name": "Pokemon Elite Trainer Box",
        "price": 49.99,
        "status": "IN_STOCK seller=Walmart.com",
        "url": url_of("99"),
    }


def test_lookup_of_a_page_without_a_name_gives_name_none_and_the_reason(tmp_path):
    browser = WalmartBrowser(load_fixture("walmart_malformed_no_initial_data.json"))

    got = walmart.lookup(make_config(tmp_path), "99", browser)

    assert got == {"name": None, "price": None, "status": "no initialData", "url": url_of("99")}
