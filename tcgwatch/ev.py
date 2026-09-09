"""Chase-card EV for a booster box: is the box worth opening, vs. buying singles.

box EV = sum over tiers of (per_box count) x (mean market price for that tier)
verdict = box EV - box price      (positive = statistically worth opening)

v1 scope, see docs/ev-calculator-spec.md: chase-card EV only. Base/common card value is
ignored -- this answers "is the chase-card upside worth the box price", not full box EV.
Tiers with a `rarity_query` get a live TCGplayer mean price (tcgwatch/singles.py); tiers
with only a `price_estimate` use that community-sourced number instead (data/pull_rates.yaml
says which, and why). A tier with neither (price unknown) is reported but excluded from the
EV sum, not silently treated as zero.
"""

from __future__ import annotations

import functools
import time
from pathlib import Path

import yaml

from . import singles

_PULL_RATES_PATH = Path(__file__).resolve().parent.parent / "data" / "pull_rates.yaml"
_CACHE_SECONDS = 86400  # matches singles.py's own tier-price cache


def match_group(name: str) -> str | None:
    """Which pull_rates.yaml set (if any) a grouped product name belongs to, by substring
    match against each set's `match` field. Case-insensitive. None if no set configured
    for this product (most products have no pull-rate data at all -- that's expected)."""
    n = name.lower()
    for set_key, cfg in _pull_rates().items():
        needle = (cfg.get("match") or "").lower()
        if needle and needle in n:
            return set_key
    return None


def get_or_refresh(state, set_key: str, box_price: float | None) -> dict | None:
    """EV for a set, cached in state.json under ``ev:<set_key>`` for a day, so a manual
    `python watch.py --site` rebuild doesn't hit TCGplayer's singles search every time it
    runs -- same reasoning as market.py's per-product cache. Recomputes when the cache is
    stale, missing, or box_price has changed (a price move should reflect immediately in
    the verdict even if the underlying card prices haven't been re-checked yet)."""
    cache_key = f"ev:{set_key}"
    cached = state.get(cache_key)
    now = time.time()
    if cached and cached.get("box_price") == box_price and now - cached.get("_cached_at", 0) < _CACHE_SECONDS:
        return {k: v for k, v in cached.items() if k != "_cached_at"}
    result = calc_ev(set_key, box_price)
    if result is not None:
        state.update(cache_key, _cached_at=now, **result)
    return result


@functools.lru_cache(maxsize=1)
def _pull_rates() -> dict:
    try:
        raw = yaml.safe_load(_PULL_RATES_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    return raw.get("sets") or {}


def calc_ev(set_key: str, box_price: float | None) -> dict | None:
    """Return the EV breakdown for one set, or None if set_key isn't in pull_rates.yaml.

    Shape: {
        "set": display name,
        "box_price": as given,
        "ev": sum of priced tiers (None if nothing priced),
        "verdict": ev - box_price (None if either side is missing),
        "tiers": [{"name", "per_box", "price", "price_source", "contribution"}],
        "unpriced": [tier names with no price available at all],
    }
    """
    cfg = _pull_rates().get(set_key)
    if not cfg:
        return None

    game_line = cfg.get("tcgplayer_game_line") or _game_line_for(cfg.get("tcgplayer_game"))
    tcg_set_name = cfg.get("tcgplayer_set_name")

    tiers_out: list[dict] = []
    unpriced: list[str] = []
    ev_total = 0.0
    have_any_price = False

    for tier in cfg.get("tiers") or []:
        name = tier.get("name", "?")
        per_box = float(tier.get("per_box") or 0)
        price = None
        source = None

        if tier.get("rarity_query") and game_line and tcg_set_name:
            try:
                stat = singles.tier_price(game_line, tcg_set_name, tier["rarity_query"])
            except RuntimeError as e:
                stat = None
                source = f"lookup failed: {e}"
            if stat:
                price = stat["mean"]
                source = f"live TCGplayer mean, n={stat['n']}"

        if price is None and tier.get("price_estimate") is not None:
            price = float(tier["price_estimate"])
            source = tier.get("price_note") or "community estimate"

        if price is None:
            unpriced.append(name)
            tiers_out.append({"name": name, "per_box": per_box, "price": None, "price_source": tier.get("price_note") or source, "contribution": None})
            continue

        have_any_price = True
        contribution = round(per_box * price, 2)
        ev_total += contribution
        tiers_out.append({"name": name, "per_box": per_box, "price": price, "price_source": source, "contribution": contribution})

    ev = round(ev_total, 2) if have_any_price else None
    verdict = round(ev - box_price, 2) if (ev is not None and box_price is not None) else None

    return {
        "set": cfg.get("display_name", set_key),
        "box_price": box_price,
        "ev": ev,
        "verdict": verdict,
        "tiers": tiers_out,
        "unpriced": unpriced,
    }


def _game_line_for(game: str | None) -> str | None:
    # Mirrors tcgwatch/market.py's LINE dict. Kept separate (not imported) so this module
    # never needs market.py's sealed-product-search machinery, just the same slug mapping.
    return {"Pokemon": "pokemon", "One Piece": "one-piece-card-game", "Riftbound": "riftbound-league-of-legends-trading-card-game"}.get(game or "")
