"""TCGplayer singles pricing, by rarity tier, for the EV calculator (tcgwatch/ev.py).

Same endpoint as tcgwatch/market.py (TCGplayer's own site search API), but querying
Cards instead of Sealed Products, filtered by TCGplayer's own `rarityName` facet.
Verified live 2026-09-08 against Riftbound: Unleashed: Common/Uncommon/Rare/Epic/Showcase
are real, populated facets with market prices attached to every result in the sample.

This does NOT try to price a single named card -- pull-rate data (data/pull_rates.yaml)
is per rarity TIER, not per card, so what EV math needs is "what does a typical Epic pull
from this set sell for", i.e. the mean market price across every Epic single in the set.
Mean, not median: EV should reflect that one $37 Epic and one $0.36 Epic are equally
likely pulls, not just the "typical" middle card.

Cached for a day per (set, rarity), same cadence as market.py's per-product cache --
this is a slow-moving number, no need to hit TCGplayer more than once a day for it.
"""

from __future__ import annotations

import logging
import statistics
import time

import requests

log = logging.getLogger("tcgwatch.singles")

SEARCH = "https://mp-search-api.tcgplayer.com/v1/search/request"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.tcgplayer.com",
    "Referer": "https://www.tcgplayer.com/",
}
_CACHE_SECONDS = 86400  # a day, matches market.py's per-product cache lifetime
_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}


def _body(game_line: str, set_name: str, rarity: str) -> dict:
    return {
        "algorithm": "sales_synonym_v2",
        "from": 0,
        "size": 40,  # TCGplayer caps a single page around here; fine for a whole rarity tier
        "filters": {
            "term": {
                "productLineName": [game_line],
                "productTypeName": ["Cards"],
                "setName": [set_name],
                "rarityName": [rarity],
            },
            "range": {},
            "match": {},
        },
        "listingSearch": {
            "context": {"cart": {}},
            "filters": {"term": {"sellerStatus": "Live", "channelId": 0}, "range": {"quantity": {"gte": 1}}, "exclude": {"channelExclusion": 0}},
        },
        "context": {"cart": {}, "shippingCountry": "US"},
        "settings": {"useFuzzySearch": True, "didYouMean": {}},
        "sort": {},
    }


def tier_price(game_line: str, set_name: str, rarity: str) -> dict | None:
    """Live TCGplayer stats for one rarity tier in one set: {mean, median, n}, or None if
    the query returned no priced results (rarity name mismatch, or no live listings).

    ``game_line`` is a TCGplayer productLineName slug (see tcgwatch/market.py's LINE dict
    for the mapping tcgwatch uses, e.g. "riftbound-league-of-legends-trading-card-game").
    ``set_name`` must match TCGplayer's own setName facet exactly (see
    data/pull_rates.yaml's tcgplayer_set_name per set).
    """
    key = (game_line, set_name, rarity)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_SECONDS:
        return cached[1]

    # The `q` free-text query is matched alongside the filters below, not just used to pick
    # a result set -- verified 2026-09-08: appending the rarity name, or keeping the colon
    # from a display-style set name ("Riftbound: Unleashed"), drops totalResults to 0 even
    # though the exact same filters with a plain "Riftbound Unleashed" query return 36 hits.
    q = set_name.replace(":", "")
    r = requests.post(SEARCH, params={"q": q, "isList": "false"}, json=_body(game_line, set_name, rarity), headers=HEADERS, timeout=20)
    if r.status_code in (403, 429):
        raise RuntimeError(f"tcgplayer {r.status_code}")
    r.raise_for_status()
    if "json" not in (r.headers.get("content-type") or ""):
        raise RuntimeError("tcgplayer returned non-JSON (soft block)")
    results = (r.json().get("results") or [{}])[0].get("results") or []
    prices = [x.get("marketPrice") for x in results if x.get("marketPrice")]
    if not prices:
        log.warning("singles: no priced results for %s / %s / %s", game_line, set_name, rarity)
        _cache[key] = (now, None)
        return None
    out = {"mean": round(statistics.mean(prices), 2), "median": round(statistics.median(prices), 2), "n": len(prices)}
    _cache[key] = (now, out)
    return out
