"""Price trends (journey 5), pure: no I/O, no clock. Rules and worked examples: docs/trends.md.

Inputs are history series ({key: [(YYYY-MM-DD, price), ...]}, see tcgwatch/history.py
series_for) and an injected `today`. Nothing here reads a file or the real date.
"""

from __future__ import annotations

import re
import statistics
from datetime import date as date_cls, timedelta
from decimal import ROUND_FLOOR, Decimal

# Window the index and peak look at. Chosen to match history.sparkline_points' 90-day view.
WINDOW_DAYS = 90
# "Near the peak" band: an index within 5% of the window max counts as at the peak.
PEAK_BAND = 0.05
# Under 4 weeks of history the index is too thin to read as a trend.
MIN_HISTORY_DAYS = 28
# Deal ceiling = MSRP x this. Same value as `max_price_ratio` in config.yaml (README "Price sanity").
DEAL_RATIO = 1.10
# Fair ceiling = market price x this: 10% under the TCGplayer market price.
FAIR_RATIO = 0.90
# The index starts at 100 on the base date.
INDEX_BASE = 100
# A shown ceiling is money, to the cent.
CENT = Decimal("0.01")
# `kind` value in config.yaml releases: that marks a reprint.
REPRINT_KIND = "reprint"

STATUS_OK = "ok"
STATUS_EARLY = "early data"
STATUS_NONE = "no data"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _day(text: str) -> date_cls:
    return date_cls.fromisoformat(text)


def _window(series: list[tuple[str, float]], today: date_cls) -> dict[str, float]:
    start = today - timedelta(days=WINDOW_DAYS)
    return {d: p for d, p in series if start <= _day(d) <= today and p}


def game_trend(series_by_key: dict[str, list[tuple[str, float]]], today: date_cls) -> dict:
    """Index of one game's products. See docs/trends.md "Game index"."""
    windows = [w for w in (_window(s, today) for s in series_by_key.values()) if w]
    if not windows:
        return {"status": STATUS_NONE, "base_date": None, "history_days": 0,
                "index": [], "peak": None}
    base_date = min(min(w) for w in windows)
    members = [w for w in windows if base_date in w]
    by_day: dict[str, list[float]] = {}
    for w in members:
        for d, p in w.items():
            by_day.setdefault(d, []).append(p / w[base_date])
    index = [(d, round(INDEX_BASE * statistics.median(r), 1)) for d, r in sorted(by_day.items())]
    history_days = (_day(index[-1][0]) - _day(base_date)).days
    early = history_days < MIN_HISTORY_DAYS
    return {"status": STATUS_EARLY if early else STATUS_OK, "base_date": base_date,
            "history_days": history_days, "index": index,
            "peak": None if early else peak_of(index)}


def peak_of(index: list[tuple[str, float]]) -> dict | None:
    """Latest point whose index is within PEAK_BAND of the window max."""
    if not index:
        return None
    top = max(v for _, v in index)
    floor = top - top * PEAK_BAND
    day, value = [(d, v) for d, v in index if v >= floor][-1]
    return {"date": day, "index": value, "max": top, "at_peak": day == index[-1][0]}


def trends_by_game(series_by_key: dict[str, list[tuple[str, float]]],
                   games: dict[str, str], today: date_cls) -> dict[str, dict]:
    """{game: game_trend} for every game that has a key in `games`."""
    grouped: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for key, series in series_by_key.items():
        game = games.get(key)
        if game:
            grouped.setdefault(game, {})[key] = series
    return {g: game_trend(s, today) for g, s in grouped.items()}


def deal_bands(msrp: float | None, market: float | None,
               deal_ratio: float = DEAL_RATIO) -> dict:
    """Ceilings a typed price is compared against; None when the input is unknown."""
    return {"deal_below": msrp * deal_ratio if msrp else None,
            "fair_below": market * FAIR_RATIO if market else None}


def price_band(price: float, bands: dict) -> str:
    """'deal' at or under deal_below, else 'fair' at or under fair_below, else 'high'."""
    if bands["deal_below"] is not None and price <= bands["deal_below"]:
        return "deal"
    if bands["fair_below"] is not None and price <= bands["fair_below"]:
        return "fair"
    return "high"


def shown_ceiling(value: float) -> float:
    """A ceiling as money, rounded down to the cent so the shown price still gets its verdict.

    54.989 shows as 54.98: the page must not print $54.99, which is not a deal. Decimal of the float's
    repr avoids binary-float tails (0.29 x 100 = 28.999999999999996).
    """
    return float(Decimal(str(value)).quantize(CENT, rounding=ROUND_FLOOR))


def band_display(bands: dict) -> dict:
    """Everything the page prints about the ceilings, so the browser only compares a price to them.

    * deal_shown, fair_shown: each ceiling rounded down to the cent, None when unknown.
    * fair_line: the fair ceiling gets its own line only when it is above the deal ceiling; otherwise
      every price it would cover is already a deal.
    * high_band, high_shown: the ceiling a 'high' price is over, the larger one ('fair' when equal).
    See docs/trends.md "Deal bands".
    """
    deal, fair = bands["deal_below"], bands["fair_below"]
    fair_leads = fair is not None and (deal is None or fair >= deal)
    high = fair if fair_leads else deal
    return {
        "deal_shown": None if deal is None else shown_ceiling(deal),
        "fair_shown": None if fair is None else shown_ceiling(fair),
        "fair_line": fair is not None and (deal is None or fair > deal),
        "high_band": None if high is None else ("fair" if fair_leads else "deal"),
        "high_shown": None if high is None else shown_ceiling(high),
    }


def _norm(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def drop_risk(product_name: str, game: str, releases: list[dict], today: date_cls) -> dict | None:
    """Earliest upcoming reprint release of the product's set, else None."""
    name = _norm(product_name)
    hits = []
    for r in releases:
        if r.get("kind") != REPRINT_KIND or _norm(r.get("game", "")) != _norm(game):
            continue
        if _day(str(r["date"])) < today or _norm(r["name"]) not in name:
            continue
        hits.append(r)
    if not hits:
        return None
    first = min(hits, key=lambda r: str(r["date"]))
    return {"release": first["name"], "date": str(first["date"])}
