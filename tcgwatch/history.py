"""Daily market-price history per product group (roadmap items 2/3).

Storage: an append-only JSONL file at ``<data_dir>/price_history.jsonl``, one line per
(date, group key): ``{"date": "YYYY-MM-DD", "key": "...", "price": 12.34}``. Appended,
never rewritten in place -- cheap, crash-safe, and small enough for this project's
scale (a handful of products x a few years of daily rows is a few thousand lines) that
reading the whole file back is fine. A duplicate (date, key) is resolved at read time by
keeping the last one written, so a re-run of anything that writes twice for the same day
is harmless.

Going forward, one row per product per day falls out naturally: watcher.py's market tick
already only refreshes a given product once every 86400 seconds (see
Watcher.run_market_tick), so calling record() from there doesn't need its own throttling.

Backfilling the past uses tcgcsv.com's dated archives (see tcgwatch/tcgcsv.py) -- real
history back to 2024-02-08, not a guess.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

from . import tcgcsv

log = logging.getLogger("tcgwatch.history")

FILENAME = "price_history.jsonl"


def _path(data_dir: Path) -> Path:
    return Path(data_dir) / FILENAME


def record(data_dir: Path, key: str, price: float | None, on: str | None = None) -> None:
    """Append one day's price for one product group. `on` defaults to today (local
    date); pass an explicit YYYY-MM-DD when backfilling a past day."""
    if price is None:
        return
    day = on or date_cls.today().isoformat()
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"date": day, "key": key, "price": price}) + "\n")


def read_all(data_dir: Path) -> dict[str, dict[str, float]]:
    """Every recorded series, as {key: {date: price}} (last write wins per date)."""
    path = _path(data_dir)
    if not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.setdefault(row["key"], {})[row["date"]] = row["price"]
    return out


def series_for(data_dir: Path, key: str) -> list[tuple[str, float]]:
    """One product's history as a date-sorted list of (date, price)."""
    rows = read_all(data_dir).get(key, {})
    return sorted(rows.items())


def change_pct(series: list[tuple[str, float]], days: int) -> float | None:
    """% change from the closest available price ~`days` ago to the latest price.
    None if there's nothing that old yet."""
    if len(series) < 2:
        return None
    latest_date, latest_price = series[-1]
    cutoff = (datetime.fromisoformat(latest_date) - timedelta(days=days)).date().isoformat()
    older = [p for d, p in series if d <= cutoff]
    if not older or not latest_price:
        return None
    base = older[-1]
    if not base:
        return None
    return round((latest_price - base) / base * 100, 1)


def sparkline_points(series: list[tuple[str, float]], days: int = 90) -> list[float]:
    """Last `days` worth of prices, oldest first, for a simple sparkline. Downsampled
    to at most ~30 points so the SVG stays small on phones."""
    cutoff_dt = datetime.fromisoformat(series[-1][0]) - timedelta(days=days) if series else None
    pts = [p for d, p in series if cutoff_dt is None or datetime.fromisoformat(d) >= cutoff_dt]
    if len(pts) > 30:
        step = len(pts) / 30
        pts = [pts[int(i * step)] for i in range(30)]
    return pts


# -- backfill from tcgcsv.com's dated archives ------------------------------------------

def backfill(cfg, days: int = 90, delay: float = 1.5) -> dict:
    """Backfill daily history for every product group that already has a resolved
    TCGplayer product_id (i.e. the watcher's ongoing market tick has matched it at least
    once -- see state.json's `market:<key>` entries). Skips a (date, key) already on
    disk, so re-running this only fills gaps.

    `delay` paces requests to tcgcsv.com's archive endpoint -- a real per-day download,
    not a burst; still worth spacing out since each call fetches a ~4 MB whole-catalog
    file the first time a given date is touched (cached to disk after that, see
    tcgwatch.tcgcsv.archive_prices).

    Returns a small report dict for the CLI to print: {products, days_attempted,
    rows_written, groups_unresolved, blocked}. `blocked` is True if a tcgcsv.com WAF
    challenge stopped the run early (see tcgwatch.tcgcsv.WafBlocked) -- whatever was
    written before that point is kept, but the run does not continue or retry.
    """
    from . import grouping
    from .state import State

    state = State(Path(cfg.data_dir) / "state.json")
    tcgcsv.set_archive_cache_dir(Path(cfg.data_dir) / "tcgcsv_cache")
    existing = read_all(cfg.data_dir)

    targets: dict[str, tuple[int, int, int]] = {}
    unresolved: list[str] = []
    rows_written = 0
    blocked = False

    try:
        # Resolve each product group to (category_id, group_id, product_id) once up front.
        seen_keys: set[str] = set()
        for p in cfg.products:
            key = grouping.group_key(p.name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            m = state.get(f"market:{key}")
            product_id = m.get("product_id")
            if not product_id:
                continue  # never matched yet; nothing to backfill until the live tick finds it
            category_id = tcgcsv.CATEGORY_ID.get(grouping.game_of(p.name))
            if not category_id:
                continue
            group = tcgcsv.find_group(category_id, grouping.market_query(p.name))
            group_id = group["groupId"] if group else None
            if group_id is None:
                # Last resort: a whole-category productId->groupId index, built once (not
                # once per product) and cached -- see tcgcsv.product_group_index.
                group_id = tcgcsv.product_group_index(category_id).get(product_id)
            if group_id is None:
                unresolved.append(key)
                continue
            targets[key] = (category_id, group_id, int(product_id))

        today = date_cls.today()
        for i in range(1, days + 1):  # start at yesterday -- today's archive is never published yet
            day = (today - timedelta(days=i)).isoformat()
            # Group targets by (category_id, group_id) so one date's archive is opened once
            # per set, not once per product, when several tracked products share a set.
            by_group: dict[tuple[int, int], list[tuple[str, int]]] = {}
            for key, (cat, grp, pid) in targets.items():
                if day in existing.get(key, {}):
                    continue  # already have this day
                by_group.setdefault((cat, grp), []).append((key, pid))
            if not by_group:
                continue
            for (cat, grp), members in by_group.items():
                prices = tcgcsv.archive_prices(day, cat, grp)
                if prices is None:
                    continue
                for key, pid in members:
                    row = prices.get(pid)
                    if row and row.get("marketPrice") is not None:
                        record(cfg.data_dir, key, row["marketPrice"], on=day)
                        existing.setdefault(key, {})[day] = row["marketPrice"]
                        rows_written += 1
            time.sleep(delay)
    except tcgcsv.WafBlocked as e:
        log.warning("tcgcsv.com blocked this run (%s); stopping, keeping what was already written", e)
        blocked = True

    return {"products": len(targets), "days_attempted": days, "rows_written": rows_written,
            "groups_unresolved": unresolved, "blocked": blocked}
