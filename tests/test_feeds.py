"""Unit tests for the Reddit deal-feed matching rules (tcgwatch/feeds.py).

Oracle: README "Reddit feeds" (a keyword match on a new post's title raises a hit) and README
"When an alert fires" (posts younger than 1 hour, a silent first look at a subreddit, a 10 minute
pause after a 429). Posts are hand-built below; no request is made (fetch_new is replaced, or
requests.get is replaced with a canned Atom feed) and the clock is the conftest `clock`, never
real. The state is the real tcgwatch.state.State on a file in tmp_path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tcgwatch import feeds as feeds_mod
from tcgwatch.feeds import FeedRule, check, fetch_new, price_in
from tcgwatch.state import State
from tests.conftest import CLOCK_START

NOW = CLOCK_START
HOUR = 3600


def post(post_id, title, age_s=60, url=None):
    return {
        "id": post_id,
        "title": title,
        "created": NOW - age_s,
        "permalink": f"https://www.reddit.com/r/x/comments/{post_id}/",
        "url": url or f"https://shop.test/{post_id}",
    }


def fresh_state(tmp_path):
    return State(tmp_path / "state.json")


def primed_state(tmp_path, *subreddits):
    """A state that has already seen each subreddit once, so the next fetch can raise hits."""
    state = fresh_state(tmp_path)
    for sub in subreddits:
        state.update(f"reddit:{sub}", seen=[], recent=[])
    return state


@pytest.fixture
def reddit(monkeypatch):
    """Maps subreddit -> list of posts (or an exception to raise) that fetch_new will return."""
    posts = {}

    def fake_fetch_new(sub, limit=25, cfg=None):
        result = posts[sub]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(feeds_mod, "fetch_new", fake_fetch_new)
    return posts


# -- FeedRule.matches: keyword hits in a title ---------------------------------------------


@pytest.mark.parametrize(
    "keywords, title, expected",
    [
        (["etb"], "[Target] Pokemon ETB back in stock $49.99", True),
        (["ETB"], "pokemon etb restock", True),                 # keyword case does not matter
        (["etb"], "POKEMON ETB RESTOCK", True),                 # title case does not matter
        (["pokemon center"], "Pokemon Center restock live", True),
        (["etb", "booster box"], "Booster Box at GameStop", True),  # any one keyword is enough
        (["etb"], "One Piece starter deck in stock", False),
        ([], "Pokemon ETB restock", False),                     # no keywords: nothing to match
    ],
)
def test_rule_matches_title_by_keyword_ignoring_case(keywords, title, expected):
    assert FeedRule("PokemonTCG", keywords).matches(title) is expected


@pytest.mark.parametrize("excluded_title", ["Pokemon ETB restock (sold out)", "SOLD OUT Pokemon ETB"])
def test_exclude_word_vetoes_an_otherwise_matching_title(excluded_title):
    rule = FeedRule("PokemonTCG", ["etb"], exclude=["sold out"])

    assert rule.matches(excluded_title) is False


def test_exclude_does_not_affect_titles_without_the_excluded_word():
    rule = FeedRule("PokemonTCG", ["etb"], exclude=["sold out"])

    assert rule.matches("Pokemon ETB restock") is True


@pytest.mark.parametrize("written", ["PokemonTCG", "r/PokemonTCG", "/r/PokemonTCG/", "PokemonTCG/"])
def test_subreddit_name_is_taken_without_r_prefix_or_slashes(written):
    assert FeedRule(written, ["etb"]).subreddit == "PokemonTCG"


# -- price_in: the price quoted in a title ---------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Pokemon ETB $49.99 at Target", 49.99),
        ("Pokemon ETB $ 49.99 at Target", 49.99),
        ("Booster bundle $27 shipped", 27.0),
        ("Was $59.99, now $29.99", 59.99),   # the first price in the title
        ("Pokemon ETB restock at Target", None),
    ],
)
def test_price_in_reads_first_dollar_amount_or_none(title, expected):
    assert price_in(title) == expected


# -- check(): which posts become hits ----------------------------------------------------------


def test_new_matching_post_is_a_hit_carrying_its_subreddit(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "[Target] Pokemon ETB back $49.99")]
    rules = [FeedRule("PokemonTCG", ["etb"])]

    hits = check(rules, primed_state(tmp_path, "PokemonTCG"))

    assert [(h["id"], h["subreddit"], h["title"]) for h in hits] == [("a1", "PokemonTCG", "[Target] Pokemon ETB back $49.99")]


def test_non_matching_post_is_not_a_hit(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Look at my binder collection")]

    hits = check([FeedRule("PokemonTCG", ["etb"])], primed_state(tmp_path, "PokemonTCG"))

    assert hits == []


def test_excluded_post_is_not_a_hit(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB sold out everywhere")]
    rules = [FeedRule("PokemonTCG", ["etb"], exclude=["sold out"])]

    assert check(rules, primed_state(tmp_path, "PokemonTCG")) == []


def test_only_matching_posts_in_a_mixed_batch_are_hits_in_order(reddit, tmp_path):
    reddit["PokemonTCG"] = [
        post("a1", "Pokemon ETB restock"),
        post("a2", "Pikachu plush photo"),
        post("a3", "Booster bundle at Walmart"),
    ]
    rules = [FeedRule("PokemonTCG", ["etb", "booster bundle"])]

    hits = check(rules, primed_state(tmp_path, "PokemonTCG"))

    assert [h["id"] for h in hits] == ["a1", "a3"]


def test_post_seen_on_an_earlier_round_is_not_a_hit_again(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB restock")]
    rules = [FeedRule("PokemonTCG", ["etb"])]
    state = primed_state(tmp_path, "PokemonTCG")
    check(rules, state)  # the earlier round: a1 is a hit and is marked seen

    second = check(rules, state)

    assert second == []


def test_non_matching_post_is_still_marked_seen(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Look at my binder")]
    state = primed_state(tmp_path, "PokemonTCG")

    check([FeedRule("PokemonTCG", ["etb"])], state)

    assert state.get("reddit:PokemonTCG")["seen"] == ["a1"]


def test_post_older_than_max_age_is_not_a_hit(reddit, tmp_path):
    reddit["PokemonTCG"] = [
        post("old", "Pokemon ETB restock", age_s=HOUR + 1),
        post("fresh", "Pokemon ETB restock", age_s=HOUR - 1),
    ]

    hits = check([FeedRule("PokemonTCG", ["etb"])], primed_state(tmp_path, "PokemonTCG"))

    assert [h["id"] for h in hits] == ["fresh"]


def test_post_exactly_one_hour_old_is_still_a_hit(reddit, tmp_path):
    # README "When an alert fires": feed posts up to 1 hour old.
    reddit["PokemonTCG"] = [post("edge", "Pokemon ETB restock", age_s=HOUR)]

    hits = check([FeedRule("PokemonTCG", ["etb"])], primed_state(tmp_path, "PokemonTCG"))

    assert [h["id"] for h in hits] == ["edge"], "a post exactly 1 hour old is still in the window"


def test_max_age_is_adjustable(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB restock", age_s=600)]

    hits = check([FeedRule("PokemonTCG", ["etb"])], primed_state(tmp_path, "PokemonTCG"), max_age_s=300)

    assert hits == []


def test_first_look_at_a_subreddit_raises_no_hits_but_marks_posts_seen(reddit, tmp_path):
    # A subreddit with no saved state is a cold start: its backlog is recorded, not alerted
    # (check() skips `first_run`), so a restart does not ping about posts already on the page.
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB restock")]
    state = fresh_state(tmp_path)

    hits = check([FeedRule("PokemonTCG", ["etb"])], state)

    assert hits == []
    assert state.get("reddit:PokemonTCG")["seen"] == ["a1"]


def test_rule_for_one_subreddit_ignores_posts_in_another(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "One Piece box restock")]
    reddit["OnePieceTCG"] = [post("b1", "One Piece box restock")]
    rules = [FeedRule("PokemonTCG", ["etb"]), FeedRule("OnePieceTCG", ["box"])]

    hits = check(rules, primed_state(tmp_path, "PokemonTCG", "OnePieceTCG"))

    assert [(h["subreddit"], h["id"]) for h in hits] == [("OnePieceTCG", "b1")]


def test_one_subreddit_failing_to_fetch_does_not_stop_the_others(reddit, tmp_path):
    reddit["OnePieceTCG"] = RuntimeError("boom")
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB restock")]
    rules = [FeedRule("OnePieceTCG", ["etb"]), FeedRule("PokemonTCG", ["etb"])]
    state = primed_state(tmp_path, "PokemonTCG", "OnePieceTCG")

    hits = check(rules, state)

    assert [h["id"] for h in hits] == ["a1"]
    assert state.get("reddit:OnePieceTCG")["seen"] == []


def test_two_rules_on_one_subreddit_yield_one_hit_per_post(reddit, tmp_path):
    reddit["PokemonTCG"] = [post("a1", "Pokemon ETB booster bundle restock")]
    rules = [FeedRule("PokemonTCG", ["etb"]), FeedRule("PokemonTCG", ["booster bundle"])]

    hits = check(rules, primed_state(tmp_path, "PokemonTCG"))

    assert [h["id"] for h in hits] == ["a1"]


# -- fetch_new over the public RSS: Atom entries become posts ---------------------------------

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_link1</id>
    <title>  [GameStop] Pokemon ETB $49.99  </title>
    <link href="https://www.reddit.com/r/PokemonTCG/comments/link1/"/>
    <updated>2026-10-05T12:00:00+00:00</updated>
    <content type="html">&lt;a href="https://www.gamestop.com/products/etb.html"&gt;[link]&lt;/a&gt; &lt;a href="https://www.reddit.com/r/PokemonTCG/comments/link1/"&gt;[comments]&lt;/a&gt;</content>
  </entry>
  <entry>
    <id>t3_self1</id>
    <title>Discussion: when is the next restock?</title>
    <link href="https://www.reddit.com/r/PokemonTCG/comments/self1/"/>
    <updated>2026-10-05T13:30:00+00:00</updated>
    <content type="html">&lt;p&gt;text only&lt;/p&gt;</content>
  </entry>
</feed>
"""


class FakeFeedResponse:
    def __init__(self, status_code=200, body=ATOM):
        self.status_code = status_code
        self.content = body.encode("utf-8")
        self.headers = {}
        self.text = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")


@pytest.fixture
def rss(monkeypatch):
    """requests.get inside feeds returns a canned Atom feed with the status the test sets."""
    state = SimpleNamespace(status=200, requests=[])

    def fake_get(url, params=None, headers=None, timeout=None):
        state.requests.append(url)
        return FakeFeedResponse(state.status)

    monkeypatch.setattr(feeds_mod.requests, "get", fake_get)
    monkeypatch.setattr(feeds_mod, "_backoff_until", {})
    monkeypatch.setattr(feeds_mod, "_warned_no_creds", True)
    return state


def test_rss_entries_become_posts_with_title_and_time(rss):
    posts = fetch_new("PokemonTCG")

    assert [p["id"] for p in posts] == ["t3_link1", "t3_self1"]
    assert posts[0]["title"] == "[GameStop] Pokemon ETB $49.99"
    assert posts[0]["created"] == datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc).timestamp()


def test_rss_link_post_points_at_the_store_and_self_post_at_reddit(rss):
    posts = fetch_new("PokemonTCG")

    assert posts[0]["url"] == "https://www.gamestop.com/products/etb.html"
    assert posts[1]["url"] == "https://www.reddit.com/r/PokemonTCG/comments/self1/"


def test_rss_429_returns_no_posts(rss):
    rss.status = 429

    posts = fetch_new("PokemonTCG")

    assert posts == []


RSS_PAUSE_S = 10 * 60  # README "When an alert fires": a 429 on the RSS feed pauses it 10 minutes


def test_rss_subreddit_that_answered_429_is_still_paused_a_second_before_10_minutes(rss, clock):
    rss.status = 429
    fetch_new("PokemonTCG")  # the 429 that starts the pause
    rss.status = 200
    clock.advance(RSS_PAUSE_S - 1)

    posts = fetch_new("PokemonTCG")

    assert posts == []
    assert len(rss.requests) == 1, "the paused subreddit was requested again before 10 minutes"


def test_rss_pause_ends_a_second_after_10_minutes(rss, clock):
    rss.status = 429
    fetch_new("PokemonTCG")
    rss.status = 200
    clock.advance(RSS_PAUSE_S + 1)

    posts = fetch_new("PokemonTCG")

    assert len(posts) == 2


def test_rss_pause_is_per_subreddit(rss):
    rss.status = 429
    fetch_new("PokemonTCG")
    rss.status = 200

    posts = fetch_new("OnePieceTCG")

    assert len(posts) == 2


# --- Reddit API transport (README "When an alert fires": pause as long as x-ratelimit-reset says,
# 60 s without the header, and early once fewer than 5 requests are left) -----------------------

API_CFG = SimpleNamespace(reddit_client_id="id", reddit_client_secret="secret", reddit_user_agent="tests")
API_LISTING = {"data": {"children": [{"data": {"name": "t3_a1", "title": "Pokemon ETB $49.99",
                                               "created_utc": NOW - 60, "permalink": "/r/x/comments/a1/",
                                               "url": "https://shop.test/a1"}}]}}


class FakeApiResponse:
    def __init__(self, status_code, headers):
        self.status_code = status_code
        self.headers = headers

    def json(self):
        return API_LISTING

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")


@pytest.fixture
def api(monkeypatch):
    """requests.get inside feeds answers like the Reddit API with the status and headers the test sets."""
    state = SimpleNamespace(status=200, headers={}, requests=0)

    def fake_get(url, params=None, headers=None, timeout=None):
        state.requests += 1
        return FakeApiResponse(state.status, state.headers)

    monkeypatch.setattr(feeds_mod.requests, "get", fake_get)
    monkeypatch.setattr(feeds_mod, "_access_token", lambda cfg: "token")
    monkeypatch.setattr(feeds_mod, "_backoff_until", {})
    return state


@pytest.mark.parametrize(
    "headers, pause_s",
    [({"x-ratelimit-reset": "120"}, 120), ({}, 60)],
    ids=["reset-header-120s", "no-header-60s"],
)
def test_api_429_pauses_as_long_as_the_reset_header_says(api, clock, headers, pause_s):
    api.status, api.headers = 429, headers
    fetch_new("PokemonTCG", cfg=API_CFG)
    api.status, api.headers = 200, {}

    clock.advance(pause_s - 1)
    still_paused = fetch_new("PokemonTCG", cfg=API_CFG)
    clock.advance(2)
    resumed = fetch_new("PokemonTCG", cfg=API_CFG)

    assert still_paused == [], f"asked again {pause_s - 1} s into a {pause_s} s pause"
    assert [p["id"] for p in resumed] == ["t3_a1"], f"not asked again {pause_s + 1} s after a {pause_s} s pause"


@pytest.mark.parametrize("remaining, paused", [("4", True), ("5", False)], ids=["4-left-pauses", "5-left-keeps-going"])
def test_api_pauses_early_once_fewer_than_5_requests_are_left(api, clock, remaining, paused):
    api.headers = {"x-ratelimit-remaining": remaining, "x-ratelimit-reset": "30"}
    first = fetch_new("PokemonTCG", cfg=API_CFG)
    api.headers = {}

    clock.advance(29)
    second = fetch_new("PokemonTCG", cfg=API_CFG)

    assert [p["id"] for p in first] == ["t3_a1"], "the answer that reports the low count is still used"
    assert (second == []) is paused, f"{remaining} requests left: paused={paused} expected"
