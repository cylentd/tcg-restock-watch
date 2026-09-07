"""Target: redsky JSON API, plain HTTP, batched (one request for every TCIN).

Verified live 2026-09-06 by capturing the key from target.com's own requests.
  product_summary_with_fulfillment_v1  -> stock for many tcins in one call
  pdp_client_v1                        -> price for one tcin
"""

from __future__ import annotations

import html
import json
import logging
import time

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


def fetch_details(cfg: Config, tcin: str) -> tuple[float | None, str | None]:
    """One pdp_client_v1 call: (list price, primary image URL)."""
    r = requests.get(BASE + "pdp_client_v1", params=_params(cfg, tcin=tcin), headers=HEADERS, timeout=20)
    if not r.ok:
        return None, None
    prod = r.json().get("data", {}).get("product", {})
    price = prod.get("price", {})
    image = prod.get("item", {}).get("enrichment", {}).get("images", {}).get("primary_image_url")
    return price.get("current_retail") or price.get("reg_retail"), image


def fetch_price(cfg: Config, tcin: str) -> float | None:
    return fetch_details(cfg, tcin)[0]


# List price and image per TCIN, refreshed at most once a day and at most one product
# per poll, so the columns fill in without adding more than one request per cycle.
_details_cache: dict[str, tuple[float | None, str | None, float]] = {}
PRICE_TTL_S = 86400


def _cached_details(cfg: Config, tcin: str, force: bool, budget: list[int]) -> tuple[float | None, str | None]:
    price, image, ts = _details_cache.get(tcin, (None, None, 0.0))
    stale = time.time() - ts > PRICE_TTL_S
    if (force and price is None) or (stale and budget[0] > 0):
        budget[0] -= 1
        price, image = fetch_details(cfg, tcin)
        _details_cache[tcin] = (price, image, time.time())
    return price, image


BLOCK_BACKOFF_S = 900
BLOCK_BACKOFF_MAX_S = 4 * 3600
_block = {"until": 0.0, "backoff": BLOCK_BACKOFF_S, "loaded": False}


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


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    if not products:
        return []
    _load_block(cfg)
    if time.time() < _block["until"]:
        return [Result(p, None, None, product_url(p), "rate limited, backing off") for p in products]
    by_id = {p.id: p for p in products}
    r = requests.get(
        BASE + "product_summary_with_fulfillment_v1",
        params=_params(cfg, tcins=",".join(by_id)),
        headers=HEADERS,
        timeout=20,
    )
    if r.status_code == 403 and "captcha" in r.text.lower():
        # Redsky rate limit. Bursts trigger it; one poll per 90 s does not. A retry that hits the
        # captcha again extends the block, so the pause doubles each time (15 min up to 4 h).
        pause = _block["backoff"]
        _block["until"] = time.time() + pause
        _block["backoff"] = min(pause * 2, BLOCK_BACKOFF_MAX_S)
        _save_block(cfg)
        log.warning("target rate limited (captcha); pausing Target for %d min", pause // 60)
        return [Result(p, None, None, product_url(p), "rate limited") for p in products]
    if _block["backoff"] != BLOCK_BACKOFF_S:
        _block["backoff"] = BLOCK_BACKOFF_S
        _save_block(cfg)
    if not r.ok:
        log.warning("target HTTP %s", r.status_code)
        return [Result(p, None, None, product_url(p), f"HTTP {r.status_code}") for p in products]

    results = []
    seen = set()
    budget = [1]
    for summary in r.json().get("data", {}).get("product_summaries", []):
        tcin = str(summary.get("tcin"))
        p = by_id.get(tcin)
        if not p:
            continue
        seen.add(tcin)
        ship = summary.get("fulfillment", {}).get("shipping_options", {})
        status = ship.get("availability_status", "UNKNOWN")
        marketplace = bool(summary.get("item", {}).get("fulfillment", {}).get("is_marketplace"))
        if marketplace:
            # Target Plus third-party seller: scalper pricing, never treat as a drop.
            results.append(Result(p, False, None, product_url(p), f"{status} (marketplace seller, ignored)"))
            continue
        in_stock = status in IN_STOCK_STATUSES
        price, image = _cached_details(cfg, tcin, force=in_stock, budget=budget)
        results.append(Result(p, in_stock, price, product_url(p), status, image))
    for tcin, p in by_id.items():
        if tcin not in seen:
            results.append(Result(p, None, None, product_url(p), "not in response"))
    return results


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


def lookup(cfg: Config, tcin: str) -> dict:
    """Return name/price/status for a TCIN, for `watch.py --lookup target <tcin>`."""
    r = requests.get(BASE + "pdp_client_v1", params=_params(cfg, tcin=tcin), headers=HEADERS, timeout=20)
    r.raise_for_status()
    prod = r.json()["data"]["product"]
    item = prod.get("item", {})
    vendors = item.get("product_vendors") or []
    seller = vendors[0].get("vendor_name") if vendors else "Target"
    marketplace = bool(item.get("fulfillment", {}).get("is_marketplace"))
    return {
        "name": html.unescape(item["product_description"]["title"]),
        "price": prod.get("price", {}).get("current_retail"),
        "seller": f"{seller} (MARKETPLACE: watcher ignores this item)" if marketplace else "Target",
        "status": check([Product("target", tcin, tcin)], cfg)[0].note,
        "url": product_url(Product("target", tcin, tcin)),
    }
