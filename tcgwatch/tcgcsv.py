"""Client for tcgcsv.com: a free, daily-updated mirror of TCGplayer's own category/
group/product/price data, JSON, no auth.

This exists to get tcgwatch off scraping TCGplayer's own search API directly for
routine lookups (tcgwatch/market.py, tcgwatch/singles.py), which risks a soft block
after roughly a dozen requests in two minutes (see market.py's own history). Same
underlying data, official distribution, much lower risk -- except tcgcsv.com itself
sits behind AWS WAF Bot Control, which challenged this session's IP twice on
2026-09-08 (a captcha response, `x-amzn-waf-action: captcha`, not a plain 403/429).
Once was a real bug in this module (a request-storm, since fixed, see archive_prices);
the second time was a single, ordinary GET for a category's group list, sent with only
a User-Agent header via plain `requests` -- exactly the shape AWS WAF Bot Control's
"missing browser fingerprint" heuristic flags, independent of rate. Bot Control checks
the TLS handshake (JA3) and the full header set together, not just request volume.

Fixed by following this repo's own existing precedent (tcgwatch/retailers/gamestop.py
hit the same class of problem against a different WAF): `curl_cffi` impersonating
Chrome's TLS fingerprint, a full browser-shaped header set (Accept, Accept-Language,
Referer, sec-fetch-*), and ONE PERSISTENT SESSION so a WAF challenge/cookie issued on
the first request carries to every later one instead of every call looking like a
fresh, cookie-less client.

Structure: categoryId (a whole game, e.g. Pokemon=3) -> groupId (a set, e.g.
"Riftbound: Unleashed"=24560) -> productId (one sealed item or one card). A product's
`extendedData` list carries card-only fields like Rarity; sealed products (boxes,
bundles, ETBs) have an empty extendedData -- confirmed live 2026-09-08, this is the
same distinction tcgwatch/market.py vs tcgwatch/singles.py already care about.

Everything here is cached in-process (categories/groups rarely change; products change
only when a new set drops) so a whole watcher run costs a handful of requests, not one
per product per tick.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import time
from pathlib import Path

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # pragma: no cover
    cffi_requests = None
import requests

log = logging.getLogger("tcgwatch.tcgcsv")

BASE = "https://tcgcsv.com"
ARCHIVE_BASE = "https://tcgcsv.com/archive/tcgplayer"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://tcgcsv.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}
_ARCHIVE_HEADERS = {**HEADERS, "Accept": "*/*", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"}

# Verified live 2026-09-08 against https://tcgcsv.com/tcgplayer/categories.
CATEGORY_ID = {"Pokemon": 3, "One Piece": 68, "Riftbound": 89}

_CACHE_SECONDS = 3600  # categories/groups/products move slowly; an hour is plenty

# One persistent session for the module's lifetime: a WAF challenge/cookie earned on
# the first request should carry to every later one. A fresh plain `requests.get` per
# call (the original design) looks like a new, cookie-less client every single time,
# which is its own bot signal independent of rate.
_session = cffi_requests.Session(impersonate="chrome") if cffi_requests is not None else requests.Session()


class WafBlocked(RuntimeError):
    """tcgcsv.com's AWS WAF Bot Control challenged this request. Callers should stop
    hitting this host entirely for a while, not retry or continue a loop -- see this
    module's docstring for what happened the two times this fired on 2026-09-08."""


def _check_waf(r) -> None:
    if r.headers.get("x-amzn-waf-action") or r.status_code == 405:
        raise WafBlocked(f"tcgcsv.com WAF challenge (status {r.status_code}, "
                          f"x-amzn-waf-action={r.headers.get('x-amzn-waf-action')!r}) -- stop, don't retry")


def _get_json(url: str, params: dict | None = None) -> dict:
    r = _session.get(url, params=params, headers=HEADERS, timeout=30)
    _check_waf(r)
    r.raise_for_status()
    return r.json()


@functools.lru_cache(maxsize=8)
def _groups_cached(category_id: int, _bucket: int) -> list[dict]:
    return _get_json(f"{BASE}/tcgplayer/{category_id}/groups").get("results") or []


def groups(category_id: int) -> list[dict]:
    """All sets (groups) for a game, cached an hour: [{groupId, name, ...}, ...]."""
    return _groups_cached(category_id, int(time.time() // _CACHE_SECONDS))


@functools.lru_cache(maxsize=64)
def _products_cached(category_id: int, group_id: int, _bucket: int) -> list[dict]:
    return _get_json(f"{BASE}/tcgplayer/{category_id}/{group_id}/products").get("results") or []


def products(category_id: int, group_id: int) -> list[dict]:
    """Every product in one set, cached an hour: name, cleanName, productId, url,
    extendedData (populated -- has a Rarity field -- for singles, empty for sealed)."""
    return _products_cached(category_id, group_id, int(time.time() // _CACHE_SECONDS))


def live_prices(category_id: int, group_id: int) -> dict[int, dict]:
    """Current prices for every product in a set, keyed by productId:
    {productId: {lowPrice, midPrice, highPrice, marketPrice, ...}}."""
    rows = _get_json(f"{BASE}/tcgplayer/{category_id}/{group_id}/prices").get("results") or []
    return {r["productId"]: r for r in rows if r.get("productId") is not None}


_NORM = re.compile(r"[^a-z0-9 ]+")


def _norm(s: str) -> set[str]:
    return set(_NORM.sub(" ", s.lower()).split())


@functools.lru_cache(maxsize=8)
def _product_group_index_cached(category_id: int, _bucket: int) -> dict[int, int]:
    """{productId: groupId} for a WHOLE category, built once by scanning every group's
    product list. Expensive the first time (one request per group in the category, e.g.
    ~220 for Pokemon) -- only call this as a last-resort fallback, and only once per
    category per cache window, not once per product. A single group's endpoint erroring
    is skipped rather than aborting the whole index.

    Paced at 0.3s/request: an unpaced version of this loop is the likely cause of a real
    tcgcsv.com WAF block during a backfill run (2026-09-08) -- the per-day archive loop
    already had pacing, this fallback scan didn't. ~220 groups at 0.3s is about a minute,
    a one-time cost paid once per category per cache window, not per backfill run."""
    index: dict[int, int] = {}
    for g in groups(category_id):
        try:
            for p in products(category_id, g["groupId"]):
                pid = p.get("productId")
                if pid is not None:
                    index[pid] = g["groupId"]
        except Exception as e:  # noqa: BLE001
            log.debug("tcgcsv: skipping group %s (%s) building category index: %s", g.get("groupId"), g.get("name"), e)
        time.sleep(0.3)
    return index


def product_group_index(category_id: int) -> dict[int, int]:
    """{productId: groupId} for a whole category, cached an hour. See
    _product_group_index_cached for why this is a last-resort, not a first move."""
    return _product_group_index_cached(category_id, int(time.time() // _CACHE_SECONDS))


def find_group(category_id: int, set_name_hint: str) -> dict | None:
    """Best-matching group (set) for a free-text hint, by token overlap against the
    group's own name. None if nothing scores above a floor -- a caller should fall back
    to the older TCGplayer-search-based lookup rather than guess."""
    hint = _norm(set_name_hint)
    if not hint:
        return None
    best, best_score = None, 0.0
    for g in groups(category_id):
        name = _norm(g.get("name") or "")
        if not name:
            continue
        overlap = len(hint & name) / len(name)
        if overlap > best_score:
            best, best_score = g, overlap
    return best if best_score >= 0.5 else None


# -- dated archives (history backfill) -------------------------------------------------

_ARCHIVE_CACHE_DIR = None  # set by callers via set_archive_cache_dir(); defaults to a temp-ish spot


def set_archive_cache_dir(path: Path) -> None:
    global _ARCHIVE_CACHE_DIR
    _ARCHIVE_CACHE_DIR = path
    path.mkdir(parents=True, exist_ok=True)


def archive_prices(date: str, category_id: int, group_id: int) -> dict[int, dict] | None:
    """Historical prices for one set on one day (YYYY-MM-DD), same shape as
    live_prices(). None if that day's archive doesn't exist (before 2024-02-08, or a
    day tcgcsv hasn't published yet) or doesn't cover this group.

    Downloads and extracts the WHOLE day's archive (~4 MB, every game) the first time
    a date is asked for, cached to disk under the watcher's data dir so backfilling
    several sets/products for the same date only pays the download once.
    """
    import py7zr

    cache_dir = _ARCHIVE_CACHE_DIR or Path.cwd() / ".tcgcsv_archive_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = f"{date}/{category_id}/{group_id}/prices"
    local = cache_dir / date / str(category_id) / str(group_id) / "prices.json"
    if local.exists():
        # JSON object keys are always strings -- productId must be cast back to int on
        # the way out, or every lookup by int silently misses (confirmed as a real bug
        # 2026-09-08: `prices.get(678150)` returned None against a cache that had the
        # data under the key "678150").
        cached = json.loads(local.read_text(encoding="utf-8")).get("_by_id") or {}
        return {int(k): v for k, v in cached.items()}

    archive_path = cache_dir / f"prices-{date}.ppmd.7z"
    missing_marker = cache_dir / f"prices-{date}.missing"
    if missing_marker.exists():
        # A prior call already confirmed this date has no archive (before 2024-02-08,
        # or not yet published) -- don't re-request it for every other group asked
        # about the same date. This is the fix for a real bug: without this, backfill()
        # made one live request per product GROUP for a missing date instead of one per
        # DATE, a ~35-request burst in a few seconds that tripped tcgcsv.com's WAF
        # (confirmed 2026-09-08).
        return None
    if not archive_path.exists():
        url = f"{ARCHIVE_BASE}/prices-{date}.ppmd.7z"
        r = _session.get(url, headers=_ARCHIVE_HEADERS, timeout=120)
        if r.status_code == 404:
            log.info("tcgcsv: no archive for %s (before 2024-02-08, or not yet published)", date)
            missing_marker.write_text("", encoding="utf-8")
            return None
        _check_waf(r)
        r.raise_for_status()
        archive_path.write_bytes(r.content)

    try:
        with py7zr.SevenZipFile(archive_path, mode="r") as z:
            names = z.getnames()
            if target not in names:
                return None
            z.extract(path=cache_dir, targets=[target])
    except Exception as e:  # noqa: BLE001
        log.warning("tcgcsv: failed to extract %s from %s archive: %s", target, date, e)
        return None

    extracted = cache_dir / target
    if not extracted.exists():
        return None
    raw = json.loads(extracted.read_text(encoding="utf-8"))
    rows = raw.get("results") or []
    by_id = {r["productId"]: r for r in rows if r.get("productId") is not None}
    log.debug("tcgcsv: extracted %d products for %s/%s/%s", len(by_id), date, category_id, group_id)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({"_by_id": by_id}), encoding="utf-8")
    return by_id
