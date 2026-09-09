"""Target: redsky JSON API, batched (one request for every TCIN), called as the browser.

Verified live 2026-09-06 by capturing the key from target.com's own requests.
  product_summary_with_fulfillment_v1  -> stock for many tcins in one call
  pdp_client_v1                        -> price and image for one tcin

Why the browser: redsky sits behind Target's bot challenge, and a cookieless client from
this IP gets the captcha 403 on most requests once it has been noticed. 2026-09-07 showed
15 captcha pauses in 14 hours and 1938 skipped polls against 321 real ones, and Chrome TLS
impersonation (curl_cffi) did not help. The watcher's headed Chrome passes the challenge
on a top-level navigation and can then call the API from page context, so when a browser
is available every redsky call goes through it. Plain HTTP remains for --lookup and
--discover, with the captcha backoff that path needs.
"""

from __future__ import annotations

import html
import json
import logging
import time
from urllib.parse import urlencode

import requests

from ..config import Config, Product
from . import Result, product_url

log = logging.getLogger("tcgwatch.target")

KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
BASE = "https://redsky.target.com/redsky_aggregations/v1/web/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.target.com/",
}
IN_STOCK_STATUSES = {"IN_STOCK", "LIMITED_STOCK", "PRE_ORDER_SELLABLE"}


def _params(cfg: Config, **extra) -> dict:
    p = {
        "key": KEY,
        "store_id": cfg.target_store_id,
        "pricing_store_id": cfg.target_store_id,
        "has_pricing_store_id": "true",
        "zip": cfg.zip_code,
        "channel": "WEB",
    }
    p.update(extra)
    return p


# -- transport ---------------------------------------------------------------------------

BLOCK_BACKOFF_S = 900
BLOCK_BACKOFF_MAX_S = 4 * 3600
_block = {"until": 0.0, "backoff": BLOCK_BACKOFF_S, "loaded": False}
CHALLENGE_PAUSE_S = 300
_challenge_until = 0.0


def _block_file(cfg: Config):
    return cfg.data_dir / "target_block.json"


def _load_block(cfg: Config) -> None:
    """Restarts must respect an active block: on 2026-09-07 five restarts in an hour each polled
    Target immediately and kept the captcha block alive for 40+ minutes."""
    if _block["loaded"]:
        return
    _block["loaded"] = True
    try:
        saved = json.loads(_block_file(cfg).read_text(encoding="utf-8"))
        _block["until"] = float(saved.get("until", 0.0))
        _block["backoff"] = int(saved.get("backoff", BLOCK_BACKOFF_S))
    except (OSError, ValueError):
        pass


def _save_block(cfg: Config) -> None:
    try:
        _block_file(cfg).write_text(json.dumps({"until": _block["until"], "backoff": _block["backoff"]}), encoding="utf-8")
    except OSError:
        pass


def _get(cfg: Config, browser, endpoint: str, **extra) -> tuple[int, dict | None, str]:
    """One redsky call. Returns (status, parsed JSON or None, note)."""
    if browser is not None:
        url = BASE + endpoint + "?" + urlencode(_params(cfg, **extra))
        try:
            return browser.fetch_json(url)
        except Exception as e:  # noqa: BLE001
            return 0, None, f"browser error: {e}"
    _load_block(cfg)
    if time.time() < _block["until"]:
        return 429, None, "rate limited, backing off"
    r = requests.get(BASE + endpoint, params=_params(cfg, **extra), headers=HEADERS, timeout=20)
    if r.status_code == 403 and "captcha" in r.text.lower():
        # A retry that hits the captcha again extends the block, so the pause doubles each
        # time (15 min up to 4 h).
        pause = _block["backoff"]
        _block["until"] = time.time() + pause
        _block["backoff"] = min(pause * 2, BLOCK_BACKOFF_MAX_S)
        _save_block(cfg)
        log.warning("target rate limited (captcha); pausing Target for %d min", pause // 60)
        return 403, None, "rate limited"
    if _block["backoff"] != BLOCK_BACKOFF_S:
        _block["backoff"] = BLOCK_BACKOFF_S
        _save_block(cfg)
    if not r.ok:
        return r.status_code, None, f"HTTP {r.status_code}"
    try:
        return 200, r.json(), "http"
    except ValueError:
        return 200, None, "bad JSON"


# -- details (price, image) --------------------------------------------------------------

def fetch_details(cfg: Config, tcin: str, browser=None) -> tuple[float | None, str | None]:
    """One pdp_client_v1 call: (list price, primary image URL)."""
    status, data, _ = _get(cfg, browser, "pdp_client_v1", tcin=tcin)
    if status != 200 or not data:
        return None, None
    prod = data.get("data", {}).get("product", {})
    price = prod.get("price", {})
    image = prod.get("item", {}).get("enrichment", {}).get("images", {}).get("primary_image_url")
    return price.get("current_retail") or price.get("reg_retail"), image


def fetch_price(cfg: Config, tcin: str, browser=None) -> float | None:
    return fetch_details(cfg, tcin, browser)[0]


# List price and image per TCIN, refreshed at most once a day and at most one product
# per poll, so the columns fill in without adding more than one request per cycle.
_details_cache: dict[str, tuple[float | None, str | None, float]] = {}
PRICE_TTL_S = 86400


def _cached_details(cfg: Config, browser, tcin: str, force: bool, budget: list[int]) -> tuple[float | None, str | None]:
    price, image, ts = _details_cache.get(tcin, (None, None, 0.0))
    stale = time.time() - ts > PRICE_TTL_S
    # `force` used to refetch every poll while an in-stock item had no price, which after a
    # failed detail call meant one extra request per in-stock product per poll. Now it only
    # jumps the queue for a product that has never been fetched.
    if (force and tcin not in _details_cache) or (stale and budget[0] > 0):
        budget[0] -= 1
        price, image = fetch_details(cfg, tcin, browser)
        _details_cache[tcin] = (price, image, time.time())
    return price, image


# -- stock check -------------------------------------------------------------------------

def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    global _challenge_until
    if not products:
        return []
    if browser is not None and time.time() < _challenge_until:
        return [Result(p, None, None, product_url(p), "captcha (paused)") for p in products]
    by_id = {p.id: p for p in products}
    status, data, note = _get(cfg, browser, "product_summary_with_fulfillment_v1", tcins=",".join(by_id))
    if status != 200 or not data:
        if browser is not None and status == 403:
            # The tab is sitting on Target's challenge page. Leave it there for the user to
            # solve and stop navigating to it every poll.
            _challenge_until = time.time() + CHALLENGE_PAUSE_S
            log.warning("target challenge not passed in the browser (%s); pausing Target %d min", note, CHALLENGE_PAUSE_S // 60)
            note = "captcha: " + note
        elif status not in (403, 429):
            log.warning("target %s", note)
        return [Result(p, None, None, product_url(p), note) for p in products]

    results = []
    seen = set()
    budget = [1]
    for summary in data.get("data", {}).get("product_summaries", []):
        tcin = str(summary.get("tcin"))
        p = by_id.get(tcin)
        if not p:
            continue
        seen.add(tcin)
        ship = summary.get("fulfillment", {}).get("shipping_options", {})
        status_txt = ship.get("availability_status", "UNKNOWN")
        marketplace = bool(summary.get("item", {}).get("fulfillment", {}).get("is_marketplace"))
        if marketplace:
            # Target Plus third-party seller: scalper pricing, never treat as a drop.
            results.append(Result(p, False, None, product_url(p), f"{status_txt} (marketplace seller, ignored)"))
            continue
        in_stock = status_txt in IN_STOCK_STATUSES
        price, image = _cached_details(cfg, browser, tcin, force=in_stock, budget=budget)
        results.append(Result(p, in_stock, price, product_url(p), status_txt, image))
    for tcin, p in by_id.items():
        if tcin not in seen:
            results.append(Result(p, None, None, product_url(p), "not in response"))
    return results


# -- CLI helpers (plain HTTP) -------------------------------------------------------------

def discover(cfg: Config, keyword: str, include_sold_out: bool = True, pages: int = 4) -> list[dict]:
    """Search Target for products sold by Target itself (marketplace excluded)."""
    found: dict[str, dict] = {}
    for offset in range(0, pages * 24, 24):
        params = _params(
            cfg,
            keyword=keyword,
            count=24,
            offset=offset,
            page=f"/s/{keyword.replace(' ', '+')}",
            store_ids=cfg.target_store_id,
            platform="desktop",
            visitor_id="01A079D3A49D020094D40EEC971FBF20",
            useragent=HEADERS["User-Agent"],
            default_purchasability_filter="false" if include_sold_out else "true",
            include_sponsored="false",
        )
        r = requests.get(BASE + "plp_search_v2", params=params, headers=HEADERS, timeout=20)
        if not r.ok:
            break
        prods = r.json().get("data", {}).get("search", {}).get("products", [])
        if not prods:
            break
        for prod in prods:
            item = prod.get("item", {})
            if item.get("fulfillment", {}).get("is_marketplace"):
                continue
            tcin = str(prod.get("tcin"))
            found[tcin] = {
                "id": tcin,
                "name": html.unescape(item.get("product_description", {}).get("title", "")),
                "price": prod.get("price", {}).get("current_retail") or prod.get("price", {}).get("reg_retail"),
                "status": prod.get("fulfillment", {}).get("shipping_options", {}).get("availability_status"),
            }
    return list(found.values())


def lookup(cfg: Config, tcin: str, browser=None) -> dict:
    """Return name/price/status for a TCIN, for `watch.py --lookup target <tcin>`."""
    status, data, note = _get(cfg, browser, "pdp_client_v1", tcin=tcin)
    if status != 200 or not data:
        raise RuntimeError(f"Target lookup failed: {note}")
    prod = data["data"]["product"]
    item = prod.get("item", {})
    vendors = item.get("product_vendors") or []
    seller = vendors[0].get("vendor_name") if vendors else "Target"
    marketplace = bool(item.get("fulfillment", {}).get("is_marketplace"))
    return {
        "name": html.unescape(item["product_description"]["title"]),
        "price": prod.get("price", {}).get("current_retail"),
        "seller": f"{seller} (MARKETPLACE: watcher ignores this item)" if marketplace else "Target",
        "status": check([Product("target", tcin, tcin)], cfg, browser)[0].note,
        "url": product_url(Product("target", tcin, tcin)),
    }
