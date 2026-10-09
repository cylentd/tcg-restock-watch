"""Status page group fields beyond the premium: image, price trend, listing order, release window.

Oracle (README "Status page"; site.py docstring): a row's thumbnail is the first retailer listing's
image, else TCGplayer's image for the matched product, and is only fetched when an image folder is
given. A trend needs two recorded days; the sheet shows the % change over 30 and over 90 days and a
sparkline of the last 90 days. Listings run Target, Best Buy, Walmart, GameStop, then any other
retailer. A release stays on the calendar for 14 days after its date. All inputs are hand-made; the
image download is stubbed so no host is touched.
"""

from datetime import timedelta

import pytest

from tcgwatch import grouping, history, site as site_mod
from tcgwatch.config import Product
from tcgwatch.state import State
from tests.builders import make_config

ETB = "Pokemon Prismatic Evolutions Elite Trainer Box"
ETB_KEY = grouping.group_key(ETB)
LISTING_IMAGE = "https://img.test/etb.jpg"


@pytest.fixture(autouse=True)
def no_ev_lookup(monkeypatch):
    monkeypatch.setattr(site_mod.ev, "match_group", lambda name: None)


@pytest.fixture
def downloads(monkeypatch):
    """Stub the image download: records each URL asked for and 'saves' it as <n>.webp."""
    asked = []

    def ensure_webp(url, out_dir):
        asked.append(url)
        return f"{len(asked)}.webp"

    monkeypatch.setattr(site_mod.images, "ensure_webp", ensure_webp)
    return asked


def collect_etb(tmp_path, seen=None, img_dir=None, market=None):
    state = State(tmp_path / "state.json")
    for key, fields in (seen or {}).items():
        state.update(key, **fields)
    if market:
        state.update(f"market:{ETB_KEY}", **market)
    cfg = make_config(tmp_path, products=[Product("target", "111", ETB, msrp=49.99)])
    return site_mod.collect(cfg, img_dir)["groups"][0]


def test_the_row_image_is_the_listings_image_downloaded_into_the_image_folder(tmp_path, downloads):
    row = collect_etb(tmp_path, {"target:111": {"image": LISTING_IMAGE}}, img_dir=tmp_path / "img")

    assert downloads == [LISTING_IMAGE]
    assert row["img"] == "img/1.webp"


def test_without_a_listing_image_the_row_uses_the_tcgplayer_image_of_the_matched_product(tmp_path, downloads):
    row = collect_etb(tmp_path, img_dir=tmp_path / "img", market={"market": 75.0, "product_id": 12345})

    assert downloads == ["https://product-images.tcgplayer.com/fit-in/874x874/12345.jpg"]
    assert row["img"] == "img/1.webp"


def test_a_row_with_no_image_anywhere_has_none_and_downloads_nothing(tmp_path, downloads):
    row = collect_etb(tmp_path, img_dir=tmp_path / "img")

    assert downloads == []
    assert row["img"] is None


def test_no_image_folder_means_no_download_even_when_a_listing_has_an_image(tmp_path, downloads):
    row = collect_etb(tmp_path, {"target:111": {"image": LISTING_IMAGE}}, img_dir=None)

    assert downloads == []
    assert row["img"] is None


def test_a_failed_download_leaves_the_row_without_an_image(tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod.images, "ensure_webp", lambda url, out_dir: None)

    row = collect_etb(tmp_path, {"target:111": {"image": LISTING_IMAGE}}, img_dir=tmp_path / "img")

    assert row["img"] is None


def test_the_listing_image_url_is_not_left_on_the_page_data(tmp_path, downloads):
    row = collect_etb(tmp_path, {"target:111": {"image": LISTING_IMAGE}}, img_dir=tmp_path / "img")

    assert [sorted(l) for l in row["listings"]] == [["checked", "price", "retailer", "status", "url"]]


def record_prices(tmp_path, rows):
    for day, price in rows:
        history.record(tmp_path, ETB_KEY, price, on=day)


def test_the_trend_windows_are_30_and_90_days_back_from_the_latest_recorded_day(tmp_path):
    record_prices(tmp_path, [
        ("2026-10-15", 60.0),  # 91 days before the latest: outside the 90-day window
        ("2026-10-16", 62.0),  # exactly 90 days before
        ("2026-12-15", 65.0),  # exactly 30 days before
        ("2027-01-14", 75.0),  # latest
    ])

    trend = collect_etb(tmp_path)["history"]

    # 30d: (75 - 65) / 65 = 15.38%; 90d: (75 - 62) / 62 = 20.97%
    assert trend == {"pct30": 15.4, "pct90": 21.0, "spark": [62.0, 65.0, 75.0]}


def test_two_recorded_days_are_enough_for_a_trend(tmp_path):
    record_prices(tmp_path, [("2027-01-13", 70.0), ("2027-01-14", 75.0)])

    assert collect_etb(tmp_path)["history"] == {"pct30": None, "pct90": None, "spark": [70.0, 75.0]}


def test_one_recorded_day_is_not_a_trend(tmp_path):
    record_prices(tmp_path, [("2027-01-14", 75.0)])

    assert collect_etb(tmp_path)["history"] is None


def test_listings_run_target_bestbuy_walmart_gamestop_then_any_other_retailer(tmp_path):
    products = [Product(r, str(i), ETB, msrp=49.99) for i, r in enumerate(["pokemoncenter", "gamestop", "walmart", "bestbuy", "target"])]

    row = site_mod.collect(make_config(tmp_path, products=products))["groups"][0]

    assert [l["retailer"] for l in row["listings"]] == ["target", "bestbuy", "walmart", "gamestop", "pokemoncenter"]


@pytest.mark.parametrize(
    "days_ago, listed",
    [(14, ["Old Set"]), (15, [])],  # the last 14 days stay as "out now"
    ids=["14-days-ago-kept", "15-days-ago-dropped"],
)
def test_a_release_stays_listed_for_14_days_after_its_date(tmp_path, days_ago, listed):
    day = (site_mod.datetime.now().date() - timedelta(days=days_ago)).isoformat()
    cfg = make_config(tmp_path, releases=[{"game": "Pokemon", "name": "Old Set", "date": day}])

    releases = site_mod.collect(cfg)["releases"]

    assert [r["name"] for r in releases] == listed
