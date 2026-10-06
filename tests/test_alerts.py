"""Alert tests for Watcher.handle / run_feeds and notify.push, judged against README "Alerts".

Oracle (README): "IN STOCK: name" carries the price verdict and the store link and pings
@everyone; "Walmart wants a captcha" is sent at most every 30 min; Discord gets every alert and
ntfy gets it too when `ntfy_topic` is set; feed hits post "r/subreddit new post". An INFLATED
listing "still alerts but is not carted"; a marketplace listing counts as out of stock.

Only the HTTP transport (notify.requests.post), the cart, the default browser and the shipping
table are replaced (the clock is frozen by conftest's `clock`), so each test follows the real path
handle -> notify.push -> payload. The marketplace tests start one step earlier, at the Walmart parser.
"""

from __future__ import annotations

import pytest
import requests

from tcgwatch import msrp, notify
from tcgwatch import watcher as watcher_mod
from tcgwatch.config import Feed, Product
from tcgwatch.retailers import Result, walmart
from tests.builders import NTFY_SERVER, WEBHOOK, WalmartBrowser, load_fixture, make_config, make_watcher

STORE_URL = "https://www.target.com/p/-/A-12345"
MINUTE = 60


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = {}
        self.text = ""


@pytest.fixture(autouse=True)
def shipping_table(monkeypatch):
    """Explicit shipping table, so a verdict never depends on the shipping block in config.yaml.

    Free shipping everywhere: the price judged is the price the listing shows.
    """
    table = {"target": {"free_over": 0, "flat_fee": 0}, "walmart": {"free_over": 0, "flat_fee": 0}}
    monkeypatch.setattr(msrp, "_shipping_cfg", lambda: table)


@pytest.fixture
def sent(monkeypatch):
    """Every HTTP post notify would make, captured instead of sent."""
    calls = []

    def fake_post(url, json=None, data=None, headers=None, timeout=None, **kwargs):
        calls.append({"url": url, "json": json, "data": data, "headers": headers})
        return FakeResponse()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    return calls


@pytest.fixture
def opened(monkeypatch):
    """Pages the watcher tried to open in the user's browser; none is ever really opened."""
    urls = []
    monkeypatch.setattr(watcher_mod.webbrowser, "open", lambda url, new=0: urls.append(url) or True)
    return urls


@pytest.fixture
def carted(monkeypatch):
    """Products the watcher asked the controlled browser to add to the cart."""
    products = []

    def fake_add_to_cart(browser, product):
        products.append(product)
        return True, "https://www.target.com/cart"

    monkeypatch.setattr(watcher_mod.cart_mod, "add_to_cart", fake_add_to_cart)
    return products


def etb(retailer="target", msrp=49.99) -> Product:
    return Product(retailer, "12345", "Pokemon ETB", msrp=msrp)


def restock(product, price, url=STORE_URL) -> Result:
    return Result(product, True, price, url)


def discord_posts(sent):
    return [c for c in sent if c["url"] == WEBHOOK]


# -- IN STOCK ----------------------------------------------------------------------------


def test_restock_alert_has_title_price_verdict_and_store_link(tmp_path, sent, opened):
    w = make_watcher(tmp_path)

    w.handle(restock(etb(), 49.99))

    [post] = discord_posts(sent)
    embed = post["json"]["embeds"][0]
    assert embed["title"] == "IN STOCK: Pokemon ETB"
    assert "$49.99" in embed["description"]
    assert "INFLATED" not in embed["description"]
    assert embed["url"] == STORE_URL
    assert f"[Open]({STORE_URL})" in embed["description"]


def test_restock_alert_at_acceptable_price_pings_everyone(tmp_path, sent, opened):
    w = make_watcher(tmp_path)

    w.handle(restock(etb(), 49.99))

    [post] = discord_posts(sent)
    assert post["json"]["content"] == "@everyone"


def test_inflated_restock_alerts_without_pinging_everyone(tmp_path, sent, opened):
    # README "Alerts": an INFLATED listing alerts without the ping (David, 2026-10-06).
    w = make_watcher(tmp_path)

    w.handle(restock(etb(), 60.00))  # 60.00 > 49.99 x 1.10 = 54.989

    [post] = discord_posts(sent)
    assert post["json"]["content"] == "", "an overpriced restock must not ping @everyone"


def test_second_in_stock_poll_does_not_alert_again(tmp_path, sent, opened):
    # README "When an alert fires": only an out-of-stock -> in-stock flip alerts, so a battle
    # deck sitting in stock for hours does not ping every poll.
    w = make_watcher(tmp_path)
    w.handle(restock(etb(), 49.99))
    sent.clear()

    w.handle(restock(etb(), 49.99))

    assert sent == []


def test_restock_after_going_out_of_stock_alerts_again(tmp_path, sent, opened):
    w = make_watcher(tmp_path)
    w.handle(restock(etb(), 49.99))
    w.handle(Result(etb(), False, None, STORE_URL))
    sent.clear()

    w.handle(restock(etb(), 49.99))

    assert [c["json"]["embeds"][0]["title"] for c in discord_posts(sent)] == ["IN STOCK: Pokemon ETB"]


# -- INFLATED: alerts, but is not carted --------------------------------------------------


def test_inflated_listing_still_alerts_labelled_inflated_with_store_link(tmp_path, sent, opened):
    w = make_watcher(tmp_path)

    w.handle(restock(etb(), 60.00))  # 60.00 > 49.99 x 1.10 = 54.989

    [post] = discord_posts(sent)
    embed = post["json"]["embeds"][0]
    assert embed["title"] == "IN STOCK: Pokemon ETB"
    assert "INFLATED" in embed["description"]
    assert embed["url"] == STORE_URL


@pytest.mark.parametrize(
    "price, expected_carts",
    [(49.99, 1), (54.98, 1), (54.99, 0), (60.00, 0)],
    ids=["at-msrp", "just-under-ceiling", "just-over-ceiling", "inflated"],
)
def test_cart_auto_adds_only_listings_within_the_ceiling(tmp_path, sent, carted, price, expected_carts):
    w = make_watcher(tmp_path, cart_mode="auto")

    w.handle(restock(etb(), price))

    assert len(carted) == expected_carts, f"price {price}: carted {len(carted)}"
    assert len(discord_posts(sent)) == 1, "the alert is sent whether or not the item is carted"


@pytest.mark.parametrize(
    "price, expected_opens",
    [(49.99, [STORE_URL]), (54.99, []), (60.00, [])],
    ids=["at-msrp", "just-over-ceiling", "inflated"],
)
def test_cart_open_opens_the_page_only_within_the_ceiling(tmp_path, sent, opened, price, expected_opens):
    w = make_watcher(tmp_path, cart_mode="open")

    w.handle(restock(etb(), price))

    assert opened == expected_opens


def test_blank_msrp_listing_is_alerted_not_labelled_inflated(tmp_path, sent, opened):
    w = make_watcher(tmp_path)

    w.handle(restock(etb(msrp=None), 300.00))

    [post] = discord_posts(sent)
    assert "INFLATED" not in post["json"]["embeds"][0]["description"]


# -- marketplace counts as out of stock ---------------------------------------------------


def read_walmart_page(tmp_path, fixture) -> Result:
    """What the Walmart parser makes of a product page, the Result the watcher is then handed."""
    product = Product("walmart", "99", "Pokemon ETB", msrp=49.99)
    [result] = walmart.check([product], make_config(tmp_path), WalmartBrowser(load_fixture(fixture)))
    return result


def test_marketplace_seller_on_a_walmart_page_sends_nothing_carts_nothing_opens_nothing(tmp_path, sent, opened, carted):
    """Fixture: hand-built minimal payload; replace with a recorded answer when one is captured."""
    w = make_watcher(tmp_path, cart_mode="auto")
    listing = read_walmart_page(tmp_path, "walmart_marketplace_in_stock.json")  # in stock, sold by ScalperCo

    w.handle(listing)

    assert sent == [], "a marketplace listing must not raise an alert"
    assert carted == [], "a marketplace listing must not be carted"
    assert opened == [], "a marketplace listing must not be opened"
    assert w.state.get(listing.product.key)["in_stock"] is False


def test_walmart_selling_it_itself_on_a_walmart_page_alerts_in_stock(tmp_path, sent, opened):
    """Same path as the marketplace test, with Walmart as the seller. Fixture: hand-built minimal payload."""
    w = make_watcher(tmp_path)
    listing = read_walmart_page(tmp_path, "walmart_first_party_in_stock.json")

    w.handle(listing)

    assert alert_titles(sent) == ["IN STOCK: Pokemon ETB"]


# -- Walmart captcha: at most every 30 min -------------------------------------------------


def captcha(retailer="walmart") -> Result:
    p = Product(retailer, "99", "Pokemon ETB", msrp=49.99)
    return Result(p, None, None, f"https://www.{retailer}.com/ip/99", "captcha")


def alert_titles(sent):
    return [c["json"]["embeds"][0]["title"] for c in discord_posts(sent)]


def test_captcha_alert_names_the_retailer_and_links_the_page(tmp_path, sent):
    w = make_watcher(tmp_path)

    w.handle(captcha())

    [post] = discord_posts(sent)
    embed = post["json"]["embeds"][0]
    assert embed["title"] == "Walmart wants a captcha"
    assert embed["url"] == "https://www.walmart.com/ip/99"


def test_captcha_alert_repeats_no_sooner_than_30_minutes(tmp_path, sent, clock):
    w = make_watcher(tmp_path)
    w.handle(captcha())

    clock.advance(29 * MINUTE + 59)
    w.handle(captcha())

    assert alert_titles(sent) == ["Walmart wants a captcha"]


def test_captcha_alert_is_sent_again_after_30_minutes(tmp_path, sent, clock):
    w = make_watcher(tmp_path)
    w.handle(captcha())

    clock.advance(30 * MINUTE + 1)
    w.handle(captcha())

    assert alert_titles(sent) == ["Walmart wants a captcha"] * 2


def test_captcha_alert_wait_restarts_from_each_alert(tmp_path, sent, clock):
    w = make_watcher(tmp_path)
    w.handle(captcha())
    clock.advance(31 * MINUTE)
    w.handle(captcha())  # second alert, 31 min after the first

    clock.advance(29 * MINUTE)  # 29 min after the second alert
    w.handle(captcha())

    assert len(discord_posts(sent)) == 2


def test_captcha_does_not_send_an_in_stock_alert(tmp_path, sent):
    w = make_watcher(tmp_path)

    w.handle(captcha())

    assert not any(t.startswith("IN STOCK") for t in alert_titles(sent))


# -- channels: Discord always, ntfy when ntfy_topic is set -----------------------------------


def test_alert_goes_to_discord_and_ntfy_when_ntfy_topic_is_set(tmp_path, sent, opened):
    w = make_watcher(tmp_path, ntfy_topic="drops-abc")

    w.handle(restock(etb(), 49.99))

    assert sorted(c["url"] for c in sent) == sorted([WEBHOOK, f"{NTFY_SERVER}/drops-abc"])


def test_ntfy_copy_carries_title_verdict_and_store_link(tmp_path, sent, opened):
    w = make_watcher(tmp_path, ntfy_topic="drops-abc")

    w.handle(restock(etb(), 49.99))

    [ntfy_post] = [c for c in sent if c["url"] == f"{NTFY_SERVER}/drops-abc"]
    assert ntfy_post["headers"]["Title"] == "IN STOCK: Pokemon ETB"
    assert ntfy_post["headers"]["Click"] == STORE_URL
    assert "$49.99" in ntfy_post["data"].decode("utf-8")


def test_alert_goes_only_to_discord_when_no_ntfy_topic(tmp_path, sent, opened):
    w = make_watcher(tmp_path, ntfy_topic=None)

    w.handle(restock(etb(), 49.99))

    assert [c["url"] for c in sent] == [WEBHOOK]


def test_failed_transport_does_not_crash_the_poll_and_state_still_records_the_restock(tmp_path, monkeypatch, opened):
    def broken_post(*args, **kwargs):
        raise requests.ConnectionError("discord unreachable")

    monkeypatch.setattr(notify.requests, "post", broken_post)
    w = make_watcher(tmp_path)

    w.handle(restock(etb(), 49.99))

    assert w.state.get(etb().key)["in_stock"] is True


def test_push_is_true_when_one_channel_accepts_even_if_the_other_fails(tmp_path, monkeypatch):
    def post(url, **kwargs):
        return FakeResponse(500 if url == WEBHOOK else 200)

    monkeypatch.setattr(notify.requests, "post", post)
    cfg = make_config(tmp_path, ntfy_topic="drops-abc")

    assert notify.push(cfg, "t", "b", STORE_URL) is True


def test_push_is_false_when_no_channel_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(notify.requests, "post", lambda url, **kwargs: FakeResponse(500))
    cfg = make_config(tmp_path, ntfy_topic="drops-abc")

    assert notify.push(cfg, "t", "b", STORE_URL) is False


# -- Reddit feed hits ---------------------------------------------------------------------


def test_feed_hit_alerts_as_subreddit_new_post_with_price_and_link(tmp_path, sent, monkeypatch):
    hit = {
        "id": "t3_x1",
        "title": "[Target] Pokemon ETB restock $49.99",
        "permalink": "https://www.reddit.com/r/PokemonTCG/comments/x1/",
        "url": "https://www.target.com/p/-/A-12345",
        "subreddit": "PokemonTCG",
    }
    monkeypatch.setattr(watcher_mod.feeds_mod, "check", lambda rules, state, cfg=None, **kw: [hit])
    w = make_watcher(tmp_path, feeds=[Feed("PokemonTCG", ["etb"])])

    w.run_feeds()

    [post] = discord_posts(sent)
    embed = post["json"]["embeds"][0]
    assert embed["title"] == "r/PokemonTCG new post"
    assert "[Target] Pokemon ETB restock $49.99" in embed["description"]
    assert embed["url"] == "https://www.target.com/p/-/A-12345"
