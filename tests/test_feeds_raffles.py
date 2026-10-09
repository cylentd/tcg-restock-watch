"""Unit tests for routing Reddit raffle posts (tcgwatch/feeds.py check + tcgwatch/notify.py raffle_alert).

Oracle: README "Alerts" (the RAFFLE alert) and "Raffle rules". A post where raffles.is_raffle is true is
a RAFFLE hit that bypasses the restock keywords, still honours the rule's exclude words and the 1-hour
freshness rule, and is stored in state under "raffles" (retailer, title, url, opens, closes, seen_at)
until 24 hours after it closes. The alert title reads "RAFFLE: <retailer> <product>", the body
"opens <time>, closes <time>" in US Pacific time. Dates are worked out by hand: the frozen clock is
2027-01-15 08:00 UTC; January is standard time, so ET is UTC-5 and "9am ET" is 14:00 UTC, and PT is
UTC-8. Nothing touches the network: fetch_new and requests.get are replaced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tcgwatch import copy_text
from tcgwatch import feeds as feeds_mod
from tcgwatch import notify
from tcgwatch.feeds import FeedRule, check
from tcgwatch.state import State
from tests.conftest import CLOCK_START

NOW = CLOCK_START
HOUR = 3600
RAFFLE_TITLE = "[Walmart] Pokemon ETB raffle opens Jan 16 at 9am ET, closes Jan 18 at 5pm ET"
# Jan 16 09:00 ET = 14:00 UTC; Jan 18 17:00 ET = 22:00 UTC.
OPENS = "2027-01-16T14:00:00+00:00"
CLOSES = "2027-01-18T22:00:00+00:00"


def post(post_id, title, body="", age_s=60):
    return {
        "id": post_id,
        "title": title,
        "body": body,
        "created": NOW - age_s,
        "permalink": f"https://www.reddit.com/r/x/comments/{post_id}/",
        "url": f"https://shop.test/{post_id}",
    }


@pytest.fixture
def reddit(monkeypatch):
    posts = {}
    monkeypatch.setattr(feeds_mod, "fetch_new", lambda sub, limit=25, cfg=None: posts[sub])
    return posts


def primed(tmp_path):
    state = State(tmp_path / "state.json")
    state.update("reddit:PokemonTCGDeals", seen=[], recent=[])
    return state


RULES = [FeedRule("PokemonTCGDeals", ["restock"], exclude=["wts"])]


def test_raffle_post_is_a_hit_even_without_a_restock_keyword(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r1", RAFFLE_TITLE)]

    hits = check(RULES, primed(tmp_path))

    assert [(h["id"], h["raffle"]["retailer"]) for h in hits] == [("r1", "Walmart")]


def test_raffle_hit_carries_the_parsed_window(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r1", RAFFLE_TITLE)]

    hit = check(RULES, primed(tmp_path))[0]

    assert (hit["raffle"]["opens"], hit["raffle"]["closes"]) == (OPENS, CLOSES)


def test_non_raffle_post_without_keyword_is_still_not_a_hit(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("n1", "Look at my binder")]

    assert check(RULES, primed(tmp_path)) == []


def test_restock_post_is_a_hit_without_a_raffle_marker(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("s1", "Target Pokemon ETB restock")]

    hits = check(RULES, primed(tmp_path))

    assert [h["id"] for h in hits] == ["s1"]
    assert "raffle" not in hits[0]


def test_raffle_found_in_the_body_counts(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r2", "Pokemon Center news", body="Request an invite until Jan 17")]

    hits = check(RULES, primed(tmp_path))

    assert [h["id"] for h in hits] == ["r2"]


def test_excluded_raffle_post_is_neither_a_hit_nor_stored(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r3", "WTS Pokemon raffle tickets Walmart")]
    state = primed(tmp_path)

    assert check(RULES, state) == []
    assert state.get("raffles") == {}


def test_raffle_older_than_an_hour_is_not_a_hit_but_is_stored(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r4", RAFFLE_TITLE, age_s=HOUR + 1)]
    state = primed(tmp_path)

    hits = check(RULES, state)

    assert hits == []
    assert [r["url"] for r in state.get("raffles")["items"]] == ["https://shop.test/r4"]


def test_raffle_exactly_one_hour_old_is_still_a_hit(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r5", RAFFLE_TITLE, age_s=HOUR)]

    assert [h["id"] for h in check(RULES, primed(tmp_path))] == ["r5"]


def test_first_look_at_a_subreddit_stores_the_raffle_but_does_not_alert(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r6", RAFFLE_TITLE)]
    state = State(tmp_path / "state.json")

    hits = check(RULES, state)

    assert hits == []
    assert len(state.get("raffles")["items"]) == 1


def test_stored_raffle_has_the_page_fields(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r1", RAFFLE_TITLE)]
    state = primed(tmp_path)

    check(RULES, state)

    assert state.get("raffles")["items"] == [{
        "retailer": "Walmart",
        "title": RAFFLE_TITLE,
        "url": "https://shop.test/r1",
        "opens": OPENS,
        "closes": CLOSES,
        "seen_at": "2027-01-15T08:00:00+00:00",
    }]


def test_a_seen_raffle_post_is_not_stored_twice(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r1", RAFFLE_TITLE)]
    state = primed(tmp_path)
    check(RULES, state)

    second = check(RULES, state)

    assert second == []
    assert len(state.get("raffles")["items"]) == 1


def test_raffle_without_a_date_opens_when_posted_and_has_no_close(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r7", "Costco Pokemon raffle announced", age_s=60)]
    state = primed(tmp_path)

    hit = check(RULES, state)[0]

    assert (hit["raffle"]["opens"], hit["raffle"]["closes"]) == ("2027-01-15T07:59:00+00:00", None)


def test_old_raffles_that_closed_over_a_day_ago_are_dropped_from_state(reddit, tmp_path):
    state = primed(tmp_path)
    state.update("raffles", items=[
        {"retailer": "Target", "title": "old", "url": "u-old", "opens": "2027-01-10T00:00:00+00:00",
         "closes": "2027-01-14T07:00:00+00:00", "seen_at": "2027-01-10T00:00:00+00:00"},
        {"retailer": "Target", "title": "open-ended", "url": "u-open", "opens": "2027-01-10T00:00:00+00:00",
         "closes": None, "seen_at": "2027-01-10T00:00:00+00:00"},
    ])
    reddit["PokemonTCGDeals"] = [post("r1", RAFFLE_TITLE)]

    check(RULES, state)

    assert [r["url"] for r in state.get("raffles")["items"]] == ["u-open", "https://shop.test/r1"]


# -- how long a raffle stays listed: until 24 h after it closes ------------------------------------

DAY_S = 86400
# Closes at NOW - 24 h exactly: Jan 14 08:00 UTC (the frozen clock is Jan 15 08:00 UTC).
CLOSED_24H_TITLE = "Walmart Pokemon raffle opens Jan 10 9am UTC closes Jan 14 8am UTC"
CLOSED_JUST_UNDER_24H_TITLE = "Walmart Pokemon raffle opens Jan 10 9am UTC closes Jan 14 8:01am UTC"
CLOSED_JUST_OVER_24H_TITLE = "Walmart Pokemon raffle opens Jan 10 9am UTC closes Jan 14 7:59am UTC"


def stored_item(url, closes_ago_s):
    closes = datetime.fromtimestamp(NOW - closes_ago_s, timezone.utc).isoformat()
    return {"retailer": "Target", "title": url, "url": url, "opens": "2027-01-01T00:00:00+00:00",
            "closes": closes, "seen_at": "2027-01-01T00:00:00+00:00"}


@pytest.mark.parametrize(
    "closes_ago_s, kept",
    [(DAY_S - 1, True), (DAY_S, True), (DAY_S + 1, False)],
    ids=["closed-1s-under-24h-ago", "closed-exactly-24h-ago", "closed-1s-over-24h-ago"],
)
def test_a_stored_raffle_stays_until_24_hours_after_it_closed(reddit, tmp_path, closes_ago_s, kept):
    state = primed(tmp_path)
    state.update("raffles", items=[stored_item("u-stored", closes_ago_s)])
    reddit["PokemonTCGDeals"] = []

    check(RULES, state)

    assert [r["url"] for r in state.get("raffles").get("items", [])] == (["u-stored"] if kept else [])


@pytest.mark.parametrize(
    "title, kept",
    [(CLOSED_JUST_UNDER_24H_TITLE, True), (CLOSED_24H_TITLE, True), (CLOSED_JUST_OVER_24H_TITLE, False)],
    ids=["closed-23h59-ago", "closed-exactly-24h-ago", "closed-24h01-ago"],
)
def test_a_new_raffle_is_stored_only_if_it_would_still_be_listed(reddit, tmp_path, title, kept):
    reddit["PokemonTCGDeals"] = [post("old1", title, age_s=2 * DAY_S)]
    state = State(tmp_path / "state.json")  # a first run: nothing stored yet

    check(RULES, state)

    assert [r["url"] for r in state.get("raffles").get("items", [])] == (["https://shop.test/old1"] if kept else [])


def test_a_first_run_over_a_busy_feed_stores_only_the_raffles_still_listed(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [
        post("long-closed", "Walmart Pokemon raffle opens Jan 1 9am UTC closes Jan 3 9am UTC", age_s=14 * DAY_S),
        post("open-now", RAFFLE_TITLE),
    ]
    state = State(tmp_path / "state.json")

    check(RULES, state)

    assert [r["url"] for r in state.get("raffles")["items"]] == ["https://shop.test/open-now"]


# -- the Reddit API body: selftext ---------------------------------------------------------------

API_CFG = SimpleNamespace(reddit_client_id="id", reddit_client_secret="secret", reddit_user_agent="tests")


class FakeApiResponse:
    status_code = 200
    headers: dict = {}

    def __init__(self, children):
        self._children = children

    def json(self):
        return {"data": {"children": [{"data": c} for c in self._children]}}

    def raise_for_status(self):
        return None


@pytest.fixture
def api(monkeypatch):
    """requests.get inside feeds answers like the Reddit API with the posts the test sets."""
    answer = SimpleNamespace(children=[])
    monkeypatch.setattr(feeds_mod.requests, "get", lambda url, **kw: FakeApiResponse(answer.children))
    monkeypatch.setattr(feeds_mod, "_access_token", lambda cfg: "token")
    monkeypatch.setattr(feeds_mod, "_backoff_until", {})
    return answer


def api_post(**fields):
    return {"name": "t3_x", "title": "Walmart Pokemon raffle", "created_utc": NOW - 60,
            "permalink": "/r/x/comments/x/", "url": "https://shop.test/x", **fields}


def test_the_api_post_body_is_its_selftext(api):
    api.children = [api_post(selftext="Entries open Jan 16 9am UTC")]

    [got] = feeds_mod.fetch_new("PokemonTCGDeals", cfg=API_CFG)

    assert got["body"] == "Entries open Jan 16 9am UTC"


@pytest.mark.parametrize("fields", [{"selftext": None}, {"selftext": ""}, {}], ids=["null", "empty", "missing"])
def test_an_api_post_without_selftext_has_an_empty_body(api, fields):
    api.children = [api_post(**fields)]

    [got] = feeds_mod.fetch_new("PokemonTCGDeals", cfg=API_CFG)

    assert got["body"] == ""


def test_a_raffle_whose_dates_are_only_in_the_selftext_is_stored_with_that_window(api, tmp_path):
    api.children = [api_post(title="Walmart Pokemon raffle",
                             selftext="Opens Jan 16 at 9am UTC. Closes Jan 18 at 5pm UTC.")]
    state = primed(tmp_path)

    check(RULES, state, API_CFG)

    [item] = state.get("raffles")["items"]
    assert (item["opens"], item["closes"]) == ("2027-01-16T09:00:00+00:00", "2027-01-18T17:00:00+00:00")


# -- the alert text ------------------------------------------------------------------------------


def test_raffle_alert_title_and_body_name_retailer_product_and_window():
    record = {"retailer": "Walmart", "title": RAFFLE_TITLE, "url": "u", "opens": OPENS, "closes": CLOSES}

    title, body = notify.raffle_alert(record)

    assert title == "RAFFLE: Walmart Pokemon ETB raffle opens Jan 16 at 9am ET, closes Jan 18 at 5pm ET"
    # Times are US Pacific (README "Alerts"): January is standard time, UTC-8.
    assert body == "opens Sat Jan 16 06:00 PST, closes Mon Jan 18 14:00 PST"


def test_raffle_alert_body_says_when_no_close_is_stated():
    record = {"retailer": "Costco", "title": "Pokemon raffle", "url": "u",
              "opens": "2027-01-15T07:59:00+00:00", "closes": None}

    _, body = notify.raffle_alert(record)

    # 07:59 UTC - 8 h = 23:59 the day before.
    assert body == "opens Thu Jan 14 23:59 PST, no close stated"


def test_raffle_alert_uses_pacific_daylight_time_in_summer():
    record = {"retailer": "Walmart", "title": "Pokemon raffle", "url": "u",
              "opens": "2026-10-12T16:00:00+00:00", "closes": "2026-10-15T06:00:00+00:00"}

    _, body = notify.raffle_alert(record)

    # October is daylight time, UTC-7: Oct 12 16:00 UTC = 09:00 PDT; Oct 15 06:00 UTC = Oct 14 23:00 PDT.
    assert body == "opens Mon Oct 12 09:00 PDT, closes Wed Oct 14 23:00 PDT"


def test_raffle_alert_title_drops_only_the_leading_retailer_tag():
    record = {"retailer": "Walmart", "title": "  [Walmart]   Pokemon ETB [wave 2] raffle", "url": "u",
              "opens": OPENS, "closes": None}

    title, _ = notify.raffle_alert(record)

    assert title == "RAFFLE: Walmart Pokemon ETB [wave 2] raffle"


def test_the_raffle_alert_wording_and_the_unknown_retailer_live_in_copy_json():
    wanted = {"raffle_title", "raffle_body", "raffle_body_no_close", "retailer_unknown"}

    assert wanted <= copy_text.load().keys()

    source = (Path(notify.__file__).read_text(encoding="utf-8")
              + Path(feeds_mod.__file__).read_text(encoding="utf-8"))
    assert "RAFFLE:" not in source and "no close stated" not in source


def test_a_raffle_post_naming_no_retailer_is_stored_under_the_unknown_retailer_copy(reddit, tmp_path):
    reddit["PokemonTCGDeals"] = [post("r8", "Pokemon raffle announced")]
    state = primed(tmp_path)

    check(RULES, state)

    assert state.get("raffles")["items"][0]["retailer"] == copy_text.load()["retailer_unknown"]
