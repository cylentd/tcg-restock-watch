"""Pokemon Center: headed browser, slow interval, alert only.

Imperva and Datadome block plain HTTP and punish fast refreshes, so the check
loads the product page in the real Chrome profile every few minutes and reads
the Add to Cart button state. Hyped drops sit behind a queue; the alert opens
the page so the user joins the queue by hand. No auto-cart here.
"""

from __future__ import annotations

import logging

from ..config import Config, Product
from . import Result, jsonld, product_url

log = logging.getLogger("tcgwatch.pokemoncenter")

BLOCK_MARKERS = ("incapsula", "access denied", "request unsuccessful", "verify you are human")
QUEUE_MARKERS = ("queue-it", "waiting room", "you are now in line")


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
            browser.wait(3000)
            cur_url = (browser.url() or "").lower()
            text = browser.body_text(4000).lower()
            if any(m in text or m in cur_url for m in BLOCK_MARKERS):
                results.append(Result(p, None, None, url, "blocked"))
                continue
            if any(m in text or m in cur_url for m in QUEUE_MARKERS):
                # A queue means a drop is live. Treat as in stock so the alert fires.
                results.append(Result(p, True, None, url, "queue active"))
                continue

            offer = jsonld.read(browser)
            if offer.found:
                results.append(Result(p, offer.in_stock, offer.price, url, offer.note, offer.image))
                continue

            price = None
            in_stock = None
            data = browser.next_data()
            if data:
                try:
                    form = data["props"]["initialState"]["product"]["addToCartForm"]
                    in_stock = bool(form.get("purchasable", form.get("available")))
                except (KeyError, TypeError):
                    pass
                try:
                    price = float(data["props"]["initialState"]["product"]["price"]["amount"])
                except (KeyError, TypeError, ValueError):
                    pass
            if in_stock is None:
                enabled = browser.button_enabled("add to cart")
                if enabled is None:
                    in_stock = False if "sold out" in text else None
                else:
                    in_stock = enabled
            note = "add-to-cart enabled" if in_stock else ("sold out" if "sold out" in text else "unavailable")
            results.append(Result(p, in_stock, price, url, note))
        except Exception as e:  # noqa: BLE001
            results.append(Result(p, None, None, url, f"browser error: {e}"))
    return results
