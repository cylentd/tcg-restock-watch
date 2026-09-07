"""Add the item to the cart in the headed browser and leave it on the cart page.

The user presses Place Order. Nothing here submits an order.
"""

from __future__ import annotations

import logging

from .browser import Browser
from .config import Product
from .retailers import CART_URLS, product_url
from .retailers.bestbuy import cart_url as bestbuy_cart_url

log = logging.getLogger("tcgwatch.cart")


def add_to_cart(browser: Browser, p: Product) -> tuple[bool, str]:
    """Return (carted, landing_url)."""
    try:
        if p.retailer == "bestbuy":
            browser.open(bestbuy_cart_url(p.id))
            browser.wait(3000)
            return True, browser.url() or CART_URLS["bestbuy"]

        if p.retailer == "pokemoncenter":
            browser.open(product_url(p))
            return False, product_url(p)

        browser.open(product_url(p))
        browser.wait(3000)
        if p.retailer == "target":
            # Verified 2026-09-06: Target defaults to store pickup when the local store has
            # stock. Select the shipping cell first so the item ships, then click the PDP
            # button by id (matching by name hits carousel buttons instead).
            browser.click_selector('button[data-test="fulfillment-cell-shipping"]')
            browser.wait(1500)
            clicked = browser.click_selector(f"#addToCartButtonOrTextIdFor{p.id}")
        else:
            clicked = browser.click_button("add to cart")
        if not clicked:
            return False, product_url(p)
        browser.wait(3000)
        browser.open(CART_URLS[p.retailer])
        browser.wait(2000)
        text = browser.body_text(2000).lower()
        if "your cart is empty" in text:
            log.warning("cart page shows empty after add for %s", p.key)
            return False, product_url(p)
        return True, CART_URLS[p.retailer]
    except Exception as e:  # noqa: BLE001
        log.warning("cart failed for %s: %s", p.key, e)
        return False, product_url(p)
