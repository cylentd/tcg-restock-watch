"""TCGplayer market price for sealed product.

TCGplayer has no public API for new developers, so this uses the search
endpoint its own site calls. Verified 2026-09-06 with a single request: sealed
results carry marketPrice, lowestPrice, medianPrice. Treat it gently: the
watcher asks for one product at a time, spaced by market_interval, and keeps
each answer for a day.
"""

from __future__ import annotations

import difflib
import logging
import re

import requests

log = logging.getLogger("tcgwatch.market")

SEARCH = "https://mp-search-api.tcgplayer.com/v1/search/request"
LINE = {"Pokemon": "pokemon", "One Piece": "one-piece-card-game", "Riftbound": "riftbound-league-of-legends-trading-card-game"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.tcgplayer.com",
    "Referer": "https://www.tcgplayer.com/",
}
_LOT_WORDS = re.compile(r"\b(display|case|lot|set of|x\d+|\d+ ?pack lot)\b", re.I)
_ALIASES = {"me": "mega evolution", "sv": "scarlet violet", "etb": "elite trainer box", "upc": "ultra premium collection"}
_STOP = {
    "the", "and", "a", "of", "pokemon", "tcg", "trading", "card", "game", "one", "piece",
    "riftbound", "league", "legends",
    # Series umbrella names our config prefixes onto every product, but TCGplayer's own set
    # field drops after the first release (set 1 is "ME01: Mega Evolution", set 4 is just
    # "ME04: Chaos Rising" — no literal "mega"/"evolution"). Requiring these words in recall
    # rejected the correct, exact-title candidate outright. Verified 2026-09-07.
    "mega", "evolution",
}


def _tokens(text: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    out: set[str] = set()
    for w in words:
        out.update(_ALIASES.get(w, w).split())
    return out - _STOP


def _body(game: str) -> dict:
    return {
        "algorithm": "sales_synonym_v2",
        "from": 0,
        "size": 24,
        "filters": {"term": {"productLineName": [LINE.get(game, "pokemon")], "productTypeName": ["Sealed Products"]}, "range": {}, "match": {}},
        "listingSearch": {
            "context": {"cart": {}},
            "filters": {"term": {"sellerStatus": "Live", "channelId": 0}, "range": {"quantity": {"gte": 1}}, "exclude": {"channelExclusion": 0}},
        },
        "context": {"cart": {}, "shippingCountry": "US"},
        "settings": {"useFuzzySearch": True, "didYouMean": {}},
        "sort": {},
    }


def product_url(product_id: int | str, url_name: str | None = None) -> str:
    return f"https://www.tcgplayer.com/product/{int(float(product_id))}" + (f"/{url_name}" if url_name else "")


def search(query: str, game: str, pin: int | None = None) -> dict | None:
    """Return the best-matching sealed product with its market price, or None.

    ``pin`` is a TCGplayer product id from config; when set, that result is taken as-is,
    skipping the name matcher (which rejects e.g. "[Set of 2]" deck names as lot listings).
    """
    r = requests.post(SEARCH, params={"q": query, "isList": "false"}, json=_body(game), headers=HEADERS, timeout=20)
    if r.status_code in (403, 429):
        raise RuntimeError(f"tcgplayer {r.status_code}")
    r.raise_for_status()
    if "json" not in (r.headers.get("content-type") or ""):
        # A challenge page instead of JSON. Seen after ~12 requests in 2 minutes on 2026-09-06.
        raise RuntimeError("tcgplayer returned non-JSON (soft block)")
    results = (r.json().get("results") or [{}])[0].get("results") or []
    if pin is not None:
        # productId arrives as a float (504257.0); compare numerically.
        best = next((x for x in results if x.get("productId") is not None and int(float(x["productId"])) == int(pin)), None)
        return _hit(best, 1.0) if best else None
    query_has_lot = bool(_LOT_WORDS.search(query))
    q_tokens = _tokens(query)
    best, best_score = None, 0.0
    for x in results:
        name = x.get("productName") or ""
        if _LOT_WORDS.search(name) and not query_has_lot:
            continue
        # Compare against set name + product name, so "Chaos Rising Booster Bundle" in set
        # "ME: Chaos Rising" beats "Mega Evolution Booster Bundle" for a Chaos Rising query.
        cand = f"{x.get('setName') or ''} {name}"
        c_tokens = _tokens(cand)
        recall = len(q_tokens & c_tokens) / len(q_tokens) if q_tokens else 0
        extra = len(c_tokens - q_tokens) / max(len(c_tokens), 1)
        ratio = difflib.SequenceMatcher(None, query.lower(), name.lower()).ratio()
        if recall < 0.85:
            # A wrong product's price is worse than no price. Every set-name word must be present.
            continue
        score = 0.6 * recall + 0.3 * ratio - 0.15 * extra
        if x.get("marketPrice") is None:
            score -= 0.2
        if score > best_score:
            best, best_score = x, score
    if not best or best_score < 0.5:
        return None
    return _hit(best, best_score)


def _hit(best: dict, score: float) -> dict:
    return {
        "product_id": best.get("productId"),
        "name": best.get("productName"),
        "set": best.get("setName"),
        "market": best.get("marketPrice"),
        "lowest": best.get("lowestPrice"),
        "median": best.get("medianPrice"),
        "url": product_url(best.get("productId"), best.get("productUrlName")),
        "score": round(score, 2),
    }
