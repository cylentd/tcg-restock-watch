"""GameStop: Salesforce Commerce Cloud JSON endpoint over plain HTTP.

Product-Variation?pid=<id> returns the product-page model: availability, price, images,
release date. Verified 2026-09-07 with a desktop User-Agent; no bot challenge at one
request every few seconds. These pages carry no third-party marketplace, so every listing
is GameStop's own. A pre-order counts as in stock only when it is orderable online;
"Pre-Order in Stores" exclusives report out of stock with an "(in-store only)" note.
"""

from __future__ import annotations

import json
import logging
import random
import subprocess
import time
import urllib.parse

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # pragma: no cover
    cffi_requests = None

from .. import NO_WINDOW
from ..config import Config, Product
from . import Result, product_url

log = logging.getLogger("tcgwatch.gamestop")

API = "https://www.gamestop.com/on/demandware.store/Sites-gamestop-us-Site/default/Product-Variation"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.gamestop.com/",
}


class Blocked(RuntimeError):
    pass


def _get(params: dict) -> tuple[int, str, str]:
    """(status, content-type, body). GameStop's edge rejects Python's TLS fingerprint with a 403
    while curl and Chrome pass (verified 2026-09-07), so impersonate Chrome via curl_cffi, or fall
    back to the system curl when that package is missing."""
    if cffi_requests is not None:
        r = cffi_requests.get(API, params=params, headers=HEADERS, impersonate="chrome", timeout=20)
        return r.status_code, r.headers.get("content-type") or "", r.text
    cmd = ["curl", "-s", "-m", "20", "-w", "\n%{http_code} %{content_type}", API + "?" + urllib.parse.urlencode(params)]
    for k, v in HEADERS.items():
        cmd += ["-H", f"{k}: {v}"]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=30, creationflags=NO_WINDOW).stdout
    body, _, tail = out.rpartition("\n")
    code, _, ctype = tail.partition(" ")
    return int(code or 0), ctype, body


def _fetch(pid: str) -> dict | None:
    """The `product` object for one id, None if GameStop has no such product."""
    status, ctype, body = _get({"pid": pid, "quantity": 1})
    if status in (403, 429):
        raise Blocked(f"HTTP {status}")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    if "json" not in ctype:
        raise Blocked("non-JSON response (challenge page?)")
    prod = (json.loads(body) or {}).get("product") or {}
    return prod if prod.get("id") else None


def _parse(p: dict) -> tuple[bool, float | None, str, str | None]:
    avail = p.get("availability") or {}
    variants = p.get("variants") or []
    v = next((x for x in variants if str(x.get("id")) == str(p.get("defaultVariantId"))), variants[0] if variants else {})
    # The master product's own available/readyToOrder are False even when its single variant is in
    # stock; defaultVariantAvailability carries the real flags (verified 2026-09-07).
    dva = p.get("defaultVariantAvailability") or {}
    orderable = bool(dva.get("available")) and bool(dva.get("readyToOrder")) and p.get("online") is not False
    in_stock = orderable and v.get("buyable") is not False
    price = None
    try:
        price = float(p["price"]["sales"]["value"])
    except (KeyError, TypeError, ValueError):
        pass
    button = str(avail.get("buttonText") or "")
    msg = str((avail.get("messages") or [""])[0])
    parts = [button.upper(), msg, str(p.get("releaseDate") or "")]
    note = " ".join(x for x in parts if x).strip()
    if p.get("isStoreExclusive") and not in_stock:
        note += " (in-store only)"
    left = dva.get("inventoryleft")
    # No unsessioned request can see GameStop's per-shopper store/shipping eligibility check, so
    # this can read in-stock when the live site (with a real session) shows sold out. A thin
    # count is the case most likely to have raced to zero between our check and yours; a smaller
    # threshold catches those without noting every high-volume item.
    if in_stock and isinstance(left, (int, float)) and left <= 10:
        note += f" ({int(left)} left, verify before buying)"
    imgs = (p.get("images") or {}).get("large") or []
    image = imgs[0].get("url") if imgs else None
    return in_stock, price, note, image


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    results: list[Result] = []
    for i, p in enumerate(products):
        url = product_url(p)
        if i:
            time.sleep(random.uniform(2, 4))
        try:
            prod = _fetch(p.id)
        except Blocked as e:
            # One block means the whole round is burned; do not keep hitting the host.
            log.warning("gamestop blocked (%s) at %s; skipping the rest this round", e, p.id)
            results.append(Result(p, None, None, url, str(e)))
            for rest in products[len(results):]:
                results.append(Result(rest, None, None, product_url(rest), f"{e} (skipped)"))
            break
        except Exception as e:  # noqa: BLE001
            results.append(Result(p, None, None, url, f"error: {e}"))
            continue
        if not prod:
            results.append(Result(p, None, None, url, "product missing"))
            continue
        in_stock, price, note, image = _parse(prod)
        results.append(Result(p, in_stock, price, url, note, image))
    return results


def lookup(cfg: Config, pid: str) -> dict:
    p = Product("gamestop", pid, pid)
    prod = _fetch(pid)
    if not prod:
        return {"name": None, "price": None, "status": "product missing", "url": product_url(p)}
    in_stock, price, note, _ = _parse(prod)
    return {"name": prod.get("productName"), "price": price, "status": f"in_stock={in_stock} {note}", "url": product_url(p)}
