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


def _browser_check(products: list[Product], cfg: Config, browser) -> list[Result]:
    results = []
    failures = 0
    for i, p in enumerate(products):
        url = product_url(p)
        if failures >= 3:
            # Three straight load errors means Best Buy is refusing this session; stop for this cycle.
            results.append(Result(p, None, None, url, "skipped after repeated load errors"))
            continue
        if i:
            # Akamai resets the connection after a burst of quick loads. Pace like a person.
            time.sleep(random.uniform(4, 9))
        try:
            browser.open(url)
            browser.wait(1500)
            info = browser.eval_json(PAGE_JS)
            if not isinstance(info, dict):
                results.append(Result(p, None, None, url, "page did not render"))
                continue
            if info.get("blocked") or "chrome-error" in str(info.get("url")):
                failures += 1
                results.append(Result(p, None, None, url, "blocked or load error"))
                continue
            failures = 0
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
            failures += 1
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
