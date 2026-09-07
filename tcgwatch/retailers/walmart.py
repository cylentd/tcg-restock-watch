"""Walmart: headed browser only (PerimeterX blocks headless and plain HTTP).

Reads the product page's __NEXT_DATA__ blob. Only "sold and shipped by Walmart"
counts as in stock, so marketplace scalper listings never trigger an alert.
Verified 2026-09-06: product pages load in a headed persistent profile; the
search page trips the "Robot or human?" challenge, so we never load it.
"""

from __future__ import annotations

import logging
import random
import time

from ..config import Config, Product
from . import Result, product_url

log = logging.getLogger("tcgwatch.walmart")

BLOCKED_MARKERS = ("robot or human", "/blocked?")


def _image(product: dict) -> str | None:
    info = product.get("imageInfo") or {}
    url = info.get("thumbnailUrl")
    if not url:
        imgs = info.get("allImages") or []
        url = imgs[0].get("url") if imgs else None
    return url


def _parse(data: dict) -> tuple[bool | None, float | None, str, str | None]:
    try:
        initial = data["props"]["pageProps"]["initialData"]
    except (KeyError, TypeError):
        return None, None, "no initialData", None
    product = (initial.get("data") or {}).get("product")
    if not product:
        errs = initial.get("errors") or []
        code = errs[0].get("extensions", {}).get("type") if errs else "no product"
        return None, None, f"product missing ({code})", None
    status = str(product.get("availabilityStatus", "")).upper()
    seller = str(product.get("sellerName", ""))
    seller_id = str(product.get("sellerId", ""))
    seller_type = str(product.get("sellerType", "")).upper()  # verified 2026-09-06: "EXTERNAL" = marketplace
    first_party = seller_type == "INTERNAL" or seller.lower() in ("walmart.com", "walmart")
    price = None
    try:
        price = float(product["priceInfo"]["currentPrice"]["price"])
    except (KeyError, TypeError, ValueError):
        pass
    in_stock = status == "IN_STOCK" and first_party
    note = f"{status} seller={seller or seller_id or '?'}" + ("" if first_party else f" at ${price} (marketplace, ignored)")
    if not first_party:
        price = None  # a reseller's price is not Walmart's price
    return in_stock, price, note, _image(product)


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    if not products:
        return []
    if browser is None:
        return [Result(p, None, None, product_url(p), "browser required") for p in products]
    results = []
    failures = 0
    for i, p in enumerate(products):
        url = product_url(p)
        if failures >= 3:
            results.append(Result(p, None, None, url, "skipped after repeated load errors"))
            continue
        if i:
            # Walmart's bot check fires on page loads a few seconds apart. Pace like a person.
            time.sleep(random.uniform(6, 12))
        try:
            browser.open(url)
            browser.wait(1200)
            cur = (browser.url() or "") + " " + (browser.title() or "")
            if any(m in cur.lower() for m in BLOCKED_MARKERS):
                results.append(Result(p, None, None, url, "captcha"))
                # One captcha blocks every Walmart item this round; stop hammering.
                for rest in products[len(results):]:
                    results.append(Result(rest, None, None, product_url(rest), "captcha (skipped)"))
                break
            data = browser.next_data()
            if not data:
                results.append(Result(p, None, None, url, "no __NEXT_DATA__"))
                continue
            in_stock, price, note, image = _parse(data)
            failures = 0
            results.append(Result(p, in_stock, price, url, note, image))
        except Exception as e:  # noqa: BLE001
            failures += 1
            results.append(Result(p, None, None, url, f"browser error: {e}"))
    return results


def lookup(cfg: Config, item_id: str, browser) -> dict:
    res = check([Product("walmart", item_id, item_id)], cfg, browser)[0]
    name = None
    try:
        name = browser.next_data()["props"]["pageProps"]["initialData"]["data"]["product"]["name"]
    except Exception:  # noqa: BLE001
        pass
    return {"name": name, "price": res.price, "status": res.note, "url": res.url}
