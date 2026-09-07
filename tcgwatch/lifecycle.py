"""Product lifecycle: what is hot, what is stale.

Hot score ranks the list. It blends the market premium (how far above MSRP the
open market sits), how often the product's set is mentioned in the deal
subreddits this week, and whether it was in stock recently.

Retired products are hidden and no longer polled. A product retires when every
retailer listing has been missing (delisted) for retire_missing_days, or when it
has not been in stock anywhere for retire_after_days since we first saw it.
"""

from __future__ import annotations

import re
import time

from . import grouping

_TYPE_WORDS = {
    "booster", "bundle", "box", "elite", "trainer", "etb", "tin", "deck", "starter", "battle", "collection",
    "premium", "ultra", "super", "pack", "blister", "sleeved", "illustration", "gift", "chest", "set", "vol",
    "poster", "sticker", "tech", "knock", "out", "double", "league", "display", "ex",
}


def set_phrase(name: str) -> str:
    """'Prismatic Evolutions Booster Bundle' -> 'prismatic evolutions'."""
    toks = [t for t in grouping.normalize(name).split() if t not in _TYPE_WORDS]
    return " ".join(toks[:3])


def buzz(name: str, titles: list[tuple[float, str]], days: int = 7) -> int:
    phrase = set_phrase(name)
    if len(phrase) < 4:
        return 0
    cutoff = time.time() - days * 86400
    pat = re.compile(re.escape(phrase).replace(r"\ ", r"\s+"), re.I)
    return sum(1 for ts, t in titles if ts >= cutoff and pat.search(t))


import re

# Product type weight, by name. Sealed volume and collector sets hold value; decks, tins and
# blisters are high-supply, low-demand and resell near MSRP (David's research, 2026-09-07).
_TYPE_WEIGHTS = (
    (re.compile(r"booster box|booster display|special collection|super[- ]premium|ultra[- ]premium|illustration box", re.I), 1.3),
    (re.compile(r"elite trainer|\betb\b", re.I), 1.2),
    (re.compile(r"blister|\btins?\b|poster|sticker|adventure chest", re.I), 0.8),
    (re.compile(r"battle deck|starter deck|deck set|ultra deck|league battle|gift box", re.I), 0.6),
)


_KINDS = (
    ("Booster Box", re.compile(r"booster box|booster display|\bdisplay\b|\bcase\b", re.I)),
    ("ETB", re.compile(r"elite trainer|\betb\b", re.I)),
    ("Bundle", re.compile(r"bundle", re.I)),
    ("Deck", re.compile(r"\bdeck", re.I)),
    ("Packs", re.compile(r"blister|booster pack|\bpacks?\b|\btins?\b|sleeved booster", re.I)),
    ("Collection", re.compile(r"collection|premium|\bbox\b|chest|poster|sticker", re.I)),
)


def product_kind(name: str) -> str:
    """Coarse product type for the site filter: Booster Box, ETB, Bundle, Deck, Packs, Collection, Other."""
    for kind, rx in _KINDS:
        if rx.search(name or ""):
            return kind
    return "Other"


def type_weight(name: str) -> float:
    for rx, w in _TYPE_WEIGHTS:
        if rx.search(name or ""):
            return w
    return 1.0


def hot_score(premium: float | None, buzz_count: int, last_in_stock: float | None, in_stock: bool, name: str = "") -> float:
    """How much the market wants this, and whether you can act on it now.

    Premium drives it. Being in stock triples the score only once the premium proves demand
    (>= 1.3x); an unpriced or at-MSRP item gets a small nudge so it surfaces without outranking
    a scalped ETB. Product type weights sealed volume and collector sets over decks and blisters.
    """
    proven = premium is not None and premium >= 1.3
    score = (premium or 1.0) * type_weight(name)
    score *= 1.0 + 0.25 * min(buzz_count, 8)
    if in_stock:
        score *= 3.0 if proven else 1.3
    elif last_in_stock and time.time() - last_in_stock < 7 * 86400:
        score *= 1.5 if proven else 1.1
    return round(score, 3)


def is_retired(entries: list[dict], retire_after_days: int, retire_missing_days: int) -> str | None:
    """Return a reason string if every listing of a product is retired, else None."""
    if not entries or retire_after_days <= 0:
        return None
    now = time.time()
    missing = [e.get("missing_since") for e in entries]
    if all(m and now - m > retire_missing_days * 86400 for m in missing):
        return "delisted by every retailer"
    first = min((e.get("first_seen") or now) for e in entries)
    last_in = max((e.get("last_in_stock") or 0.0) for e in entries)
    anchor = max(first, last_in)
    if now - anchor > retire_after_days * 86400:
        days = int((now - anchor) / 86400)
        return f"no stock anywhere for {days} days"
    return None
