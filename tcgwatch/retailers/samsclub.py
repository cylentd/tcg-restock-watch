"""Sam's Club: headed browser, schema.org first.

Probed 2026-09-08: product pages load clean through the watcher's Chrome -- real title,
no bot-check markers -- and ship a JSON-LD Product whose `offers.availability` is
accurate. That contradicts the earlier assumption that Sam's Club was unpollable; it
never was, the site was simply never tried directly.

Price comes only from JSON-LD or a selector scoped to the product's own region. There is
deliberately no page-text fallback: a Sam's Club product page carries several
recommendation carousels, and scanning the text for a price label picks up whichever
product happens to render first. A 2026-09-08 probe returned $1.47 -- the bananas -- for
a Pokemon binder. A missing price only degrades the max_price_ratio filter; a wrong one
corrupts the alert.
"""

from __future__ import annotations

import logging
import re

from ..config import Config, Product
from . import Result, jsonld, product_url

log = logging.getLogger("tcgwatch.samsclub")

# Sam's Club sits behind the same Akamai/PerimeterX stack as Walmart.
BLOCK_MARKERS = ("access denied", "request unsuccessful", "verify you are human",
                 "px-captcha", "unusual traffic", "robot or human")

# Scoped to the buy box, never the page: a bare price selector matches the carousels too.
PRICE_JS = (
    "JSON.stringify((document.querySelector(\"[data-testid='buy-box'] [itemprop='price'], "
    "[data-testid='buy-box'] [data-testid='sc-price'], "
    "main [itemprop='price']\") || {}).textContent || null)"
)


def _price_from_dom(browser) -> float | None:
    try:
        raw = browser.eval_json(PRICE_JS)
    except Exception as e:  # noqa: BLE001 - a browser hiccup is not a price
        log.debug("samsclub price eval failed: %s", e)
        return None
    if isinstance(raw, str):
        raw = raw.strip('"') or None
    if not raw:
        return None
    digits = re.sub(r"[^0-9.]", "", str(raw))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    if not products:
        return []
    if browser is None:
        return [Result(p, None, None, product_url(p), "browser required") for p in products]

    results = []
    for p in products:
        url = product_url(p)
        try:
            browser.open(url)
            browser.wait(6000)

            landed = (browser.url() or "").lower()
            text = browser.body_text(6000) or ""
            low = text.lower()
            if any(m in low or m in landed for m in BLOCK_MARKERS):
                results.append(Result(p, None, None, url, "blocked"))
                continue

            # A delisted item silently 302s to the storefront root rather than 404ing
            # (seen 2026-09-08 on item 18933156288). Without this guard the homepage
            # reads as a product page with no stock signal, and the item looks merely
            # "unavailable" forever instead of retiring.
            if p.id.lower() not in landed:
                log.info("samsclub %s redirected to %s; treating as delisted", p.id, landed)
                results.append(Result(p, None, None, url, "delisted (redirected)"))
                continue

            offer = jsonld.read(browser)
            price = offer.price if offer.price is not None else _price_from_dom(browser)

            if offer.found:
                results.append(Result(p, offer.in_stock, price, url, offer.note, offer.image))
                continue

            # No schema.org block: fall back to the buy button.
            enabled = browser.button_enabled("add to cart")
            if enabled is None:
                in_stock = False if "out of stock" in low else None
                note = "sold out" if in_stock is False else "unavailable"
            else:
                in_stock = enabled
                note = "add-to-cart enabled" if enabled else "add-to-cart disabled"
            results.append(Result(p, in_stock, price, url, note))
        except Exception as e:  # noqa: BLE001
            results.append(Result(p, None, None, url, f"browser error: {e}"))
    return results
