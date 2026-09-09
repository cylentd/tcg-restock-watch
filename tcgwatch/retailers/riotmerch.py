"""Riot Merch (merch.riotgames.com): plain HTTP, no bot challenge observed.

Next.js (App Router), not Shopify. A `requests.get` with a normal browser User-Agent to
the full `/en-us/product/<slug>/` URL returns 200 directly (verified 2026-09-07, one
request per set: Unleashed, Origins, Spiritforged, Vendetta Booster Displays, all 200,
no captcha/403). Use the full path, not the bare domain: an earlier informal check hit a
locale redirect on the root.

The product's data (name, price, availability) is not in a clean `<script
type="application/json">` tag or `window.__NEXT_DATA__` — it is embedded as an ESCAPED
JSON string inside a Next.js RSC streaming chunk (`self.__next_f.push(...)`). The page
also carries OTHER products' price/availability blocks (related-item tiles tagged
`"contentType":"product"` with a `"character"` field), so a plain first-match regex for
`availability` would grab the wrong product on most pages.

The one block anchored to the page's own product is its analytics pageview event:
  "event":"pageview","product":{"name":"...","sku":"...",
    "price":{"amount":119.99,"currencyCode":"USD"},"availability":"outOfStock","category":""}
Verified unique per page across all 4 sets checked 2026-09-07 (every other
"availability" hit on those pages belonged to a `"contentType":"product"` recommendation
tile, never a second pageview event). Anchor to this block, not the first "availability"
regex match anywhere on the page.

Purchase note (README, not enforced here): Riot limits checkout to 1 per Riot ID per
print run.
"""

from __future__ import annotations

import logging
import re

import requests

from ..config import Config, Product
from . import Result, product_url

log = logging.getLogger("tcgwatch.riotmerch")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# Anchors on the page's own analytics pageview event, which carries only that page's
# product (name/sku/price/availability together) -- not the recommendation tiles for
# other products that also appear in the RSC payload.
_PAGEVIEW = re.compile(
    r'\\"event\\":\\"pageview\\".{0,80}?\\"product\\":\{\\"name\\":\\"(?P<name>[^"\\]*(?:\\.[^"\\]*)*)\\",'
    r'\\"sku\\":\\"(?P<sku>[^"\\]*)\\",'
    r'\\"price\\":\{\\"amount\\":(?P<amount>[\d.]+),\\"currencyCode\\":\\"(?P<currency>[A-Z]+)\\"\},'
    r'\\"availability\\":\\"(?P<avail>\w+)\\"'
)


class Blocked(RuntimeError):
    pass


def _fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code in (403, 429):
        raise Blocked(f"HTTP {r.status_code}")
    r.raise_for_status()
    return r.text


def _parse(html: str) -> tuple[bool | None, float | None, str, str | None]:
    m = _PAGEVIEW.search(html)
    if not m:
        return None, None, "no pageview product block (page shape changed?)", None
    avail = m.group("avail")
    price = float(m.group("amount"))
    in_stock = {"instock": True, "outofstock": False}.get(avail.lower())
    note = f"{avail} sku={m.group('sku')}"
    if in_stock is None:
        note = f"unknown availability {avail!r}"
    return in_stock, price, note, None


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    results: list[Result] = []
    for p in products:
        url = product_url(p)
        try:
            html = _fetch(url)
        except Blocked as e:
            log.warning("riotmerch blocked (%s) at %s; skipping the rest this round", e, p.id)
            results.append(Result(p, None, None, url, str(e)))
            for rest in products[len(results):]:
                results.append(Result(rest, None, None, product_url(rest), f"{e} (skipped)"))
            break
        except Exception as e:  # noqa: BLE001
            results.append(Result(p, None, None, url, f"error: {e}"))
            continue
        in_stock, price, note, image = _parse(html)
        results.append(Result(p, in_stock, price, url, note, image))
    return results


def lookup(cfg: Config, slug: str) -> dict:
    p = Product("riotmerch", slug, slug)
    url = product_url(p)
    html = _fetch(url)
    m = _PAGEVIEW.search(html)
    name = m.group("name") if m else None
    in_stock, price, note, _ = _parse(html)
    return {"name": name, "price": price, "status": f"in_stock={in_stock} {note}", "url": url}
