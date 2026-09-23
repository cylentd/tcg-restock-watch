"""Best Buy: official Products API (free key from developer.bestbuy.com).

Falls back to a browser page check when no key is configured.
Add-to-cart uses Best Buy's own deep link: https://api.bestbuy.com/click/-/{sku}/cart
"""

from __future__ import annotations

import logging
import random
import time

import requests

from ..config import Config, Product
from . import Result, product_url

log = logging.getLogger("tcgwatch.bestbuy")

API = "https://api.bestbuy.com/v1/products"
FIELDS = "sku,name,salePrice,regularPrice,onlineAvailability,orderable,url,image"


def cart_url(sku: str) -> str:
    return f"https://api.bestbuy.com/click/-/{sku}/cart"


def _api_check(products: list[Product], cfg: Config) -> list[Result]:
    skus = ",".join(p.id for p in products)
    r = requests.get(
        f"{API}(sku in({skus}))",
        params={"apiKey": cfg.bestbuy_api_key, "format": "json", "show": FIELDS, "pageSize": 100},
        timeout=20,
    )
    if not r.ok:
        log.warning("bestbuy API HTTP %s: %s", r.status_code, r.text[:200])
        return [Result(p, None, None, product_url(p), f"HTTP {r.status_code}") for p in products]
    by_id = {p.id: p for p in products}
    results, seen = [], set()
    for item in r.json().get("products", []):
        sku = str(item.get("sku"))
        p = by_id.get(sku)
        if not p:
            continue
        seen.add(sku)
        in_stock = bool(item.get("onlineAvailability")) and str(item.get("orderable", "")).lower() == "available"
        price = item.get("salePrice") or item.get("regularPrice")
        # The official API only lists Best Buy's own offers, so no marketplace filter is needed here.
        results.append(Result(p, in_stock, price, product_url(p), str(item.get("orderable")), item.get("image")))
    for sku, p in by_id.items():
        if sku not in seen:
            results.append(Result(p, None, None, product_url(p), "not in response"))
    return results


PAGE_JS = """(()=>{
  const main = document.querySelector('main') || document.body;
  const btn = main.querySelector('button[data-testid^="pdp-add-to-cart"]');
  const text = main.innerText || '';
  const seller = (text.match(/Sold (?:&|and) shipped by\\s+([^\\n]+)/i) || [])[1] || '';
  const price = (text.match(/\\$\\s?(\\d{1,4}(?:,\\d{3})?(?:\\.\\d{2})?)/) || [])[1] || '';
  const og = document.querySelector('meta[property="og:image"]');
  const img = main.querySelector('img[src*="pisces.bbystatic.com"], img[src*="bbystatic"]');
  return JSON.stringify({
    url: location.href,
    image: (og && og.content) || (img && img.src) || '',
    hasButton: !!btn,
    enabled: btn ? !btn.disabled : null,
    label: btn ? (btn.innerText || '').trim() : '',
    seller: seller.trim(),
    price: price.replace(',', ''),
    soldOut: /sold out/i.test(text),
    comingSoon: /coming soon/i.test(text),
    blocked: /access denied|unusual traffic|are you a human/i.test(text),
  });
})()"""
# agent-browser eval on Windows chokes on multi-line scripts, so flatten it.
PAGE_JS = " ".join(line.strip() for line in PAGE_JS.splitlines())


def _load(browser, url: str) -> dict | None:
    """Navigate to a product page and return PAGE_JS's read of it, or None if it never rendered.

    Each product gets its own tab, closed afterwards. Loading Best Buy pages back to back in
    one tab leaks: measured 2026-09-21, the renderer reached 3.5 GB after 11 loads, each
    load slowed from 5 s to 50 s, and then every command hung until the pass gave up.
    `open` also waits for `load`, which Best Buy's third-party scripts stall past 30 s, so
    navigate without waiting, wait only for DOMContentLoaded, then poll for the card.
    """
    browser.run("tab", "new", "about:blank")
    try:
        browser.goto(url)
        browser.run("wait", "--load", "domcontentloaded", check=False)
        info = None
        for _ in range(4):
            browser.wait(1500)
            info = browser.eval_json(PAGE_JS)
            if not isinstance(info, dict):
                continue
            if info.get("blocked") or "chrome-error" in str(info.get("url")):
                return info
            # goto() is fire-and-forget: until the tab leaves about:blank, PAGE_JS is reading nothing.
            # (The final URL is not compared to `url`: /site/{sku}.p links redirect to /product/<slug>/<code>.)
            if "bestbuy.com" not in str(info.get("url")):
                continue
            if info.get("hasButton") or info.get("soldOut") or info.get("comingSoon") or info.get("seller"):
                return info
        return info if isinstance(info, dict) and "bestbuy.com" in str(info.get("url")) else None
    finally:
        browser.run("tab", "close", check=False)


_start = 0  # rotates the starting product each pass so a bad run never starves the same tail


def _browser_check(products: list[Product], cfg: Config, browser) -> list[Result]:
    global _start
    results = []
    blocked = errors = 0
    order = products[_start:] + products[:_start]
    _start = (_start + 8) % len(products) if products else 0
    for i, p in enumerate(order):
        url = product_url(p)
        if blocked >= 3:
            # Three straight block pages means Best Buy is refusing this session; stop for this cycle.
            results.append(Result(p, None, None, url, "skipped after repeated blocks"))
            continue
        if errors >= 6:
            # Six timeouts in one pass is a wedged browser, not slow pages; stop and let the next pass retry.
            results.append(Result(p, None, None, url, "skipped after repeated load errors"))
            continue
        if i:
            # Akamai resets the connection after a burst of quick loads. Pace like a person,
            # and back off hard after a failed load so a tarpitted session gets to recover.
            time.sleep(random.uniform(30, 45) if results and results[-1].in_stock is None else random.uniform(4, 9))
        try:
            info = _load(browser, url)
            if info is None:
                errors += 1
                results.append(Result(p, None, None, url, "page did not render"))
                continue
            if info.get("blocked") or "chrome-error" in str(info.get("url")):
                blocked += 1
                results.append(Result(p, None, None, url, "blocked or load error"))
                continue
            blocked = 0
            seller = info.get("seller") or "Best Buy"
            first_party = "best buy" in seller.lower()
            price = float(info["price"]) if info.get("price") else None
            enabled = bool(info.get("hasButton")) and bool(info.get("enabled")) and "add to cart" in info.get("label", "").lower()
            image = info.get("image") or None
            if not first_party:
                # Never report a reseller's price as Best Buy's. Keep the image, drop the price.
                results.append(Result(p, False, None, url, f"marketplace seller {seller} at ${price}, ignored", image))
                continue
            in_stock = enabled
            note = "add-to-cart enabled" if in_stock else ("sold out" if info.get("soldOut") else ("coming soon" if info.get("comingSoon") else "no add-to-cart"))
            results.append(Result(p, in_stock, price, url, note, image))
        except Exception as e:  # noqa: BLE001
            errors += 1
            results.append(Result(p, None, None, url, f"browser error: {e}"))
    return results


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    if not products:
        return []
    if cfg.bestbuy_api_key:
        return _api_check(products, cfg)
    if browser is None:
        return [Result(p, None, None, product_url(p), "no API key and no browser") for p in products]
    return _browser_check(products, cfg, browser)


def lookup(cfg: Config, sku: str) -> dict:
    if not cfg.bestbuy_api_key:
        raise RuntimeError("Set bestbuy_api_key in config.yaml (free at developer.bestbuy.com)")
    r = requests.get(f"{API}/{sku}.json", params={"apiKey": cfg.bestbuy_api_key, "show": FIELDS}, timeout=20)
    r.raise_for_status()
    item = r.json()
    return {
        "name": item.get("name"),
        "price": item.get("salePrice"),
        "status": f"online={item.get('onlineAvailability')} orderable={item.get('orderable')}",
        "url": item.get("url"),
    }
