"""Reddit deal feeds: a free, fast signal for stores we cannot poll directly.

Pokemon Center (Imperva), Costco, Sam's Club, and Amazon drops get posted to the
deal subreddits within minutes. Reddit blocks the JSON listing for scripts but
serves the Atom feed to a browser User-Agent (verified 2026-09-06). One request
per subreddit every couple of minutes is well inside its limits.
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


def fetch_new(subreddit: str, limit: int = 25) -> list[dict]:
    if time.time() < _backoff_until.get(subreddit, 0):
        return []
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


PRICE_RE = re.compile(r"\$\s?(\d{1,4}(?:\.\d{2})?)")


def price_in(title: str) -> float | None:
    m = PRICE_RE.search(title)
    return float(m.group(1)) if m else None


def check(rules: list[FeedRule], state, max_age_s: int = 3600) -> list[dict]:
    """Return new matching posts, marking every fetched post as seen in state."""
    hits = []
    now = time.time()
    for sub in sorted({r.subreddit for r in rules}):
        try:
            posts = fetch_new(sub)
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
