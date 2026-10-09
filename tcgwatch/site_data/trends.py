"""Page data for the trends section (journey 5): per-game price index and per-product price bands.

`provide(cfg, state, groups)` returns {"trends": {"games": {...}, "products": {...}}}. The groups are the
page's groups, which are hot items only (README "Hot items"), so only hot items get a band. Rules and
worked examples: docs/trends.md; the math lives in tcgwatch/trends.py and is not repeated here.

Shape: games[game] = {status, early, index [[date, value]], latest, at_peak, below_high};
       products[group key] = {deal_below, fair_below, deal_shown, fair_shown, fair_line, high_band,
       high_shown, drop_risk}. The page only compares a typed price with deal_below, then fair_below;
       everything else it prints is baked here (docs/trends.md "What the page prints").
Contract: a missing field on a group or on a game trend raises ValueError, so the build fails
instead of the page showing a blank.
"""

from __future__ import annotations

from tcgwatch import history
from tcgwatch import trends as rules

GROUP_FIELDS = ("key", "game", "name", "msrp", "market")  # what _group_listings/_enrich in site.py set
BAND_DIGITS = 3  # keeps 54.989 exact for the 54.98/54.99 boundary (docs/trends.md) without float tails
BELOW_HIGH_DIGITS = 1  # "1.5% under its 90-day high" shows one digit
PERCENT = 100
GAME_TREND_FIELDS = ("status", "index", "peak")  # what rules.game_trend returns and this module reads


def _require(obj: dict, fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        if field not in obj:
            raise ValueError(f"trends: {label} is missing '{field}'")


def _check_groups(groups: list[dict]) -> None:
    for g in groups:
        _require(g, GROUP_FIELDS, f"group {g.get('key', '?')!r}")


def _today():
    # Read through the rules module, whose date class the tests freeze (this module is re-imported
    # by the provider loader, so patching its own names would not reach it).
    return rules.date_cls.today()


def _below_high(index: list[list], peak: dict | None) -> float | None:
    """Percent the latest index is under the window high; None without a peak (no data, early data)."""
    if not peak or not index:
        return None
    return round((peak["max"] - index[-1][1]) / peak["max"] * PERCENT, BELOW_HIGH_DIGITS)


def _game_entry(trend: dict) -> dict:
    index = [list(point) for point in trend["index"]]
    peak = trend["peak"]
    return {
        "status": trend["status"],
        "early": trend["status"] == rules.STATUS_EARLY,
        "index": index,
        "latest": index[-1][1] if index else None,
        "at_peak": bool(peak and peak["at_peak"]),
        "below_high": _below_high(index, peak),
    }


def _product_entry(g: dict, ratio: float, releases: list[dict], today) -> dict:
    market = g["market"]["price"] if g["market"] else None
    bands = {k: None if v is None else round(v, BAND_DIGITS) for k, v in rules.deal_bands(g["msrp"], market, ratio).items()}
    return {**bands, **rules.band_display(bands), "drop_risk": rules.drop_risk(g["name"], g["game"], releases, today)}


def provide(cfg, state, groups: list[dict]) -> dict:
    _check_groups(groups)
    today = _today()
    all_series = history.read_all(cfg.data_dir)
    # Every group gets a series, empty when it has no history, so its game still appears ("no data").
    series = {g["key"]: sorted(all_series.get(g["key"], {}).items()) for g in groups}
    games_of = {g["key"]: g["game"] for g in groups}
    by_game = rules.trends_by_game(series, games_of, today)
    for game, trend in by_game.items():
        _require(trend, GAME_TREND_FIELDS, f"game {game!r}")
    return {"trends": {
        "games": {game: _game_entry(trend) for game, trend in sorted(by_game.items())},
        "products": {g["key"]: _product_entry(g, cfg.max_price_ratio, cfg.releases, today) for g in groups},
    }}
