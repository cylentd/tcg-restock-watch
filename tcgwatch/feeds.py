"""Reddit deal feeds: a free, fast signal for stores we cannot poll directly.

Pokemon Center (Imperva), Costco, Sam's Club, and Amazon drops get posted to the
deal subreddits within minutes.

Two transports:
  OAuth  (reddit_client_id + reddit_client_secret in config.local.yaml): the official
         JSON API with an app-only token, 100 requests a minute per app. Use this.
  RSS    (no credentials): the public Atom feed. Reddit throttles it per IP for
         non-browser clients; on 2026-09-07 it answered 429 on the first request of
         every window (x-ratelimit-remaining 0), which paused the feeds 60% of the day.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

log = logging.getLogger("tcgwatch.feeds")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
NS = {"a": "http://www.w3.org/2005/Atom"}
LINK_RE = re.compile(r'href="(https?://[^"]+)"')
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


class FeedRule:
    def __init__(self, subreddit: str, keywords: list[str], exclude: list[str] | None = None):
        self.subreddit = subreddit.strip("/").removeprefix("r/")
        self.keywords = [k.lower() for k in keywords]
        self.exclude = [k.lower() for k in (exclude or [])]

    def matches(self, title: str) -> bool:
        t = title.lower()
        if any(x in t for x in self.exclude):
            return False
        return any(k in t for k in self.keywords)


def _external_link(content_html: str, permalink: str) -> str:
    """Link posts embed the target URL in the content; self posts only link back to Reddit."""
    for href in LINK_RE.findall(content_html or ""):
        if "reddit.com" not in href and "redd.it" not in href:
            return href
    return permalink


_backoff_until: dict[str, float] = {}
BACKOFF_S = 600
_warned_no_creds = False


# -- OAuth -------------------------------------------------------------------------------

_token = {"value": None, "expires": 0.0}


def _access_token(cfg) -> str | None:
    """App-only token via the client_credentials grant; cached until a minute before expiry."""
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    r = requests.post(
        TOKEN_URL,
        auth=(cfg.reddit_client_id, cfg.reddit_client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": cfg.reddit_user_agent},
        timeout=20,
    )
    if r.status_code != 200:
        log.warning("reddit token request failed: HTTP %s %s", r.status_code, r.text[:120])
        return None
    body = r.json()
    _token["value"] = body.get("access_token")
    _token["expires"] = time.time() + float(body.get("expires_in", 3600))
    return _token["value"]


def _fetch_api(cfg, subreddit: str, limit: int) -> list[dict]:
    token = _access_token(cfg)
    if not token:
        return []
    r = requests.get(
        f"{API}/r/{subreddit}/new",
        params={"limit": limit, "raw_json": 1},
        headers={"Authorization": f"Bearer {token}", "User-Agent": cfg.reddit_user_agent},
        timeout=20,
    )
    if r.status_code == 401:
        _token["value"] = None  # expired or revoked; next call fetches a fresh one
        log.warning("reddit token rejected; refreshing next round")
        return []
    if r.status_code == 429:
        reset = float(r.headers.get("x-ratelimit-reset", 60) or 60)
        _backoff_until[subreddit] = time.time() + reset
        log.warning("reddit API rate limited on r/%s; pausing it %d s", subreddit, int(reset))
        return []
    r.raise_for_status()
    remaining = r.headers.get("x-ratelimit-remaining")
    if remaining is not None and float(remaining) < 5:
        # Stay under the window rather than run into it.
        _backoff_until[subreddit] = time.time() + float(r.headers.get("x-ratelimit-reset", 60) or 60)
    posts = []
    for child in r.json().get("data", {}).get("children", []):
        d = child.get("data", {})
        permalink = "https://www.reddit.com" + d.get("permalink", "")
        url = d.get("url") or permalink
        if d.get("is_self") or "reddit.com" in url or "redd.it" in url:
            url = permalink
        posts.append(
            {
                "id": d.get("name") or d.get("id"),
                "title": (d.get("title") or "").strip(),
                "created": float(d.get("created_utc") or time.time()),
                "permalink": permalink,
                "url": url,
            }
        )
    return posts


# -- RSS ---------------------------------------------------------------------------------

def _fetch_rss(subreddit: str, limit: int) -> list[dict]:
    r = requests.get(
        f"https://www.reddit.com/r/{subreddit}/new.rss",
        params={"limit": limit},
        headers={"User-Agent": UA, "Accept": "application/atom+xml, application/xml, */*"},
        timeout=20,
    )
    if r.status_code == 429:
        _backoff_until[subreddit] = time.time() + BACKOFF_S
        log.warning("reddit rate limited on r/%s; pausing it for %d min", subreddit, BACKOFF_S // 60)
        return []
    r.raise_for_status()
    root = ET.fromstring(r.content)
    posts = []
    for entry in root.findall("a:entry", NS):
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        permalink = ""
        link = entry.find("a:link", NS)
        if link is not None:
            permalink = link.get("href", "")
        updated = entry.findtext("a:updated", default="", namespaces=NS) or entry.findtext("a:published", default="", namespaces=NS)
        try:
            created = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        except ValueError:
            created = time.time()
        content = entry.findtext("a:content", default="", namespaces=NS) or ""
        posts.append(
            {
                "id": entry.findtext("a:id", default=permalink, namespaces=NS),
                "title": title,
                "created": created,
                "permalink": permalink,
                "url": _external_link(content, permalink),
            }
        )
    return posts


def fetch_new(subreddit: str, limit: int = 25, cfg=None) -> list[dict]:
    global _warned_no_creds
    if time.time() < _backoff_until.get(subreddit, 0):
        return []
    if cfg is not None and cfg.reddit_client_id and cfg.reddit_client_secret:
        return _fetch_api(cfg, subreddit, limit)
    if not _warned_no_creds:
        _warned_no_creds = True
        log.warning("no reddit_client_id/reddit_client_secret in config.local.yaml; using the public RSS, "
                    "which Reddit throttles hard (see README, Reddit feeds)")
    return _fetch_rss(subreddit, limit)


# -- matching ----------------------------------------------------------------------------

PRICE_RE = re.compile(r"\$\s?(\d{1,4}(?:\.\d{2})?)")


def price_in(title: str) -> float | None:
    m = PRICE_RE.search(title)
    return float(m.group(1)) if m else None


def check(rules: list[FeedRule], state, cfg=None, max_age_s: int = 3600) -> list[dict]:
    """Return new matching posts, marking every fetched post as seen in state."""
    hits = []
    now = time.time()
    for sub in sorted({r.subreddit for r in rules}):
        try:
            posts = fetch_new(sub, cfg=cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("r/%s fetch failed: %s", sub, e)
            continue
        entry = state.get(f"reddit:{sub}")
        seen = entry.get("seen", [])
        first_run = not entry
        new_seen = list(seen)
        # Keep a week of titles so the status page can rank products by how much
        # people are talking about them ("buzz").
        recent = [r for r in entry.get("recent", []) if now - r[1] < 7 * 86400]
        known = {r[0] for r in recent}
        for post in posts:
            if now - post["created"] < 7 * 86400 and post["id"] not in known:
                recent.append([post["id"], post["created"], post["title"][:140]])
            if post["id"] in seen:
                continue
            new_seen.append(post["id"])
            if first_run or now - post["created"] > max_age_s:
                continue
            for rule in rules:
                if rule.subreddit == sub and rule.matches(post["title"]):
                    hits.append({**post, "subreddit": sub})
                    break
        state.update(f"reddit:{sub}", seen=new_seen[-300:], recent=recent[-400:])
    return hits


def recent_titles(state, subreddits: list[str]) -> list[tuple[float, str]]:
    out = []
    for sub in subreddits:
        for r in state.get(f"reddit:{sub}").get("recent", []):
            out.append((r[1], r[2]))
    return out
