"""Limits and fallbacks in tcgwatch/feeds.py: the token refresh margin, the pause lengths after a
429 or a low request count, the blank-header fallback, the 401 token drop, API link mapping, the
warn-once flag, and the one-week title window that feeds buzz.

Oracle: README "Reddit feeds" and "When an alert fires" (the API pauses as long as x-ratelimit-reset
says, 60 s without the header, and early once fewer than 5 requests are left). Where the README gives
no number, the case is worked from the code's own comment and says so. Time is the conftest `clock`;
requests.get and requests.post are replaced, so nothing is sent.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import requests

from tcgwatch import feeds as feeds_mod
from tcgwatch.feeds import FeedRule, check, fetch_new, recent_titles
from tcgwatch.state import State
from tests.conftest import CLOCK_START

NOW = CLOCK_START
DAY = 86_400
HOUR = 3_600
API_CFG = SimpleNamespace(reddit_client_id="id", reddit_client_secret="secret", reddit_user_agent="tests")
EMPTY_ATOM = b'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


class Resp:
    def __init__(self, status_code=200, headers=None, body=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body if body is not None else {"data": {"children": []}}
        self.content = content
        self.text = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def isolated_feeds(monkeypatch):
    monkeypatch.setattr(feeds_mod, "_backoff_until", {})
    monkeypatch.setitem(feeds_mod._token, "value", None)
    monkeypatch.setitem(feeds_mod._token, "expires", 0.0)
    monkeypatch.setattr(feeds_mod, "_warned_no_creds", False)


@pytest.fixture
def get(monkeypatch):
    """requests.get in feeds: returns the next queued response (a plain 200 when none is queued)."""
    calls, queue = [], []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return queue.pop(0) if queue else Resp(200)

    monkeypatch.setattr(feeds_mod.requests, "get", fake_get)
    return SimpleNamespace(calls=calls, queue=queue)


@pytest.fixture
def post(monkeypatch):
    """requests.post in feeds (the token request): answers 200 with a numbered token, or `status`."""
    calls = []
    state = SimpleNamespace(calls=calls, status=200)

    def fake_post(url, auth=None, data=None, headers=None, timeout=None):
        calls.append(url)
        if state.status != 200:
            return Resp(state.status)
        return Resp(200, body={"access_token": f"tok-{len(calls)}", "expires_in": 3600})

    monkeypatch.setattr(feeds_mod.requests, "post", fake_post)
    return state


def cached_token(monkeypatch):
    """A live token, so the API path does not ask for one."""
    monkeypatch.setitem(feeds_mod._token, "value", "tok")
    monkeypatch.setitem(feeds_mod._token, "expires", NOW + HOUR)


# -- token: a token lasts expires_in, refreshed a minute before it ends ---------------------------


def test_a_successful_token_request_yields_the_token(post):
    assert feeds_mod._access_token(API_CFG) == "tok-1"
    assert len(post.calls) == 1


def test_a_failed_token_request_yields_none(post):
    post.status = 500

    assert feeds_mod._access_token(API_CFG) is None


@pytest.mark.parametrize(
    "seconds_later, refetched",
    [(3479, False), (3541, True)],
    ids=["3479s-reused", "3541s-refetched"],
)
def test_token_is_reused_until_a_minute_before_its_hour_is_up(post, clock, seconds_later, refetched):
    # expires_in 3600: the code refreshes once less than 60 s remain, so from 3540 s on.
    feeds_mod._access_token(API_CFG)
    clock.advance(seconds_later)

    token = feeds_mod._access_token(API_CFG)

    assert len(post.calls) == (2 if refetched else 1)
    assert token == ("tok-2" if refetched else "tok-1")


def test_a_401_drops_the_token_and_the_next_round_fetches_a_new_one(get, post, monkeypatch):
    monkeypatch.setitem(feeds_mod._token, "value", "old-token")
    monkeypatch.setitem(feeds_mod._token, "expires", NOW + HOUR)
    get.queue.append(Resp(401))

    assert fetch_new("PokemonTCG", cfg=API_CFG) == []
    assert feeds_mod._token["value"] is None
    assert post.calls == []

    fetch_new("PokemonTCG", cfg=API_CFG)
    assert len(post.calls) == 1


# -- pauses: a 429 holds the subreddit for exactly the header's seconds, 60 without one -----------


@pytest.mark.parametrize(
    "headers, pause_s",
    [({}, 60), ({"x-ratelimit-reset": ""}, 60), ({"x-ratelimit-reset": "90"}, 90)],
    ids=["no-header", "blank-header", "90s-header"],
)
def test_api_429_is_paused_for_exactly_the_reset_seconds(get, clock, monkeypatch, headers, pause_s):
    cached_token(monkeypatch)
    get.queue.append(Resp(429, headers=headers))
    fetch_new("PokemonTCG", cfg=API_CFG)

    clock.advance(pause_s - 1)
    fetch_new("PokemonTCG", cfg=API_CFG)
    assert len(get.calls) == 1, f"asked again 1 s before the {pause_s} s pause ended"

    clock.advance(1)
    fetch_new("PokemonTCG", cfg=API_CFG)
    assert len(get.calls) == 2, f"not asked again when the {pause_s} s pause ended"


def test_a_blank_reset_header_on_a_low_count_pauses_for_60_seconds(get, clock, monkeypatch):
    cached_token(monkeypatch)
    get.queue.append(Resp(200, headers={"x-ratelimit-remaining": "4", "x-ratelimit-reset": ""}))
    fetch_new("PokemonTCG", cfg=API_CFG)

    clock.advance(59)
    fetch_new("PokemonTCG", cfg=API_CFG)
    assert len(get.calls) == 1, "asked again 59 s into a 60 s pause"

    clock.advance(1)
    fetch_new("PokemonTCG", cfg=API_CFG)
    assert len(get.calls) == 2, "not asked again when the 60 s pause ended"


# -- API posts: the link a post points at --------------------------------------------------------


def test_api_post_keeps_an_external_link_and_points_self_and_reddit_links_at_reddit(get, monkeypatch):
    cached_token(monkeypatch)

    def child(name, title, permalink, url, is_self):
        return {"data": {"name": name, "title": title, "created_utc": NOW - 60,
                         "permalink": permalink, "url": url, "is_self": is_self}}

    get.queue.append(Resp(200, body={"data": {"children": [
        child("t3_ext", "  Pokemon ETB restock  ", "/r/PokemonTCG/comments/ext/", "https://shop.test/etb", False),
        child("t3_self", "Discussion", "/r/PokemonTCG/comments/self/",
              "https://www.reddit.com/r/PokemonTCG/comments/self/", True),
        child("t3_img", "Photo", "/r/PokemonTCG/comments/img/", "https://i.redd.it/abc.jpg", False),
    ]}}))

    posts = fetch_new("PokemonTCG", cfg=API_CFG)

    assert [(p["id"], p["title"], p["url"]) for p in posts] == [
        ("t3_ext", "Pokemon ETB restock", "https://shop.test/etb"),
        ("t3_self", "Discussion", "https://www.reddit.com/r/PokemonTCG/comments/self/"),
        ("t3_img", "Photo", "https://www.reddit.com/r/PokemonTCG/comments/img/"),
    ]


# -- no credentials: the RSS fallback warns once ----------------------------------------------------


def test_missing_credentials_warn_once_across_fetches(get, caplog):
    get.queue.extend([Resp(200, content=EMPTY_ATOM), Resp(200, content=EMPTY_ATOM)])

    with caplog.at_level(logging.WARNING, logger="tcgwatch.feeds"):
        fetch_new("PokemonTCG")
        fetch_new("OnePieceTCG")

    warnings = [r for r in caplog.records if "no reddit_client_id" in r.getMessage()]
    assert len(warnings) == 1


# -- recent titles: a week of titles, kept once each, feed buzz -------------------------------------


@pytest.fixture
def feed(monkeypatch):
    """Maps subreddit -> the posts fetch_new returns for it."""
    posts = {}
    monkeypatch.setattr(feeds_mod, "fetch_new", lambda sub, limit=25, cfg=None: posts.get(sub, []))
    return posts


def feed_post(post_id, title, age_s):
    return {"id": post_id, "title": title, "created": NOW - age_s,
            "permalink": "https://www.reddit.com/r/x/comments/p/", "url": "https://shop.test/p"}


def test_only_titles_from_the_last_seven_days_are_kept(feed, tmp_path):
    feed["PokemonTCG"] = [feed_post("fresh", "Prismatic restock", DAY), feed_post("week_old", "Prismatic restock", 8 * DAY)]
    state = State(tmp_path / "state.json")

    check([FeedRule("PokemonTCG", ["zzz"])], state)

    assert [r[0] for r in state.get("reddit:PokemonTCG")["recent"]] == ["fresh"]


def test_a_title_already_kept_is_not_kept_twice(feed, tmp_path):
    state = State(tmp_path / "state.json")
    state.update("reddit:PokemonTCG", seen=[], recent=[["fresh", NOW - DAY, "Prismatic restock"]])
    feed["PokemonTCG"] = [feed_post("fresh", "Prismatic restock", DAY)]

    check([FeedRule("PokemonTCG", ["zzz"])], state)

    assert [r[0] for r in state.get("reddit:PokemonTCG")["recent"]] == ["fresh"]


def test_recent_titles_pairs_each_kept_title_with_its_time(tmp_path):
    state = State(tmp_path / "state.json")
    state.update("reddit:PokemonTCG", seen=[], recent=[["a1", NOW - 60, "Pokemon ETB restock"]])
    state.update("reddit:OnePieceTCG", seen=[], recent=[["b1", NOW - 120, "Starter deck restock"]])

    assert recent_titles(state, ["PokemonTCG", "OnePieceTCG"]) == [
        (NOW - 60, "Pokemon ETB restock"),
        (NOW - 120, "Starter deck restock"),
    ]
