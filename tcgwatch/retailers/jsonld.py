"""Read stock and price from a page's schema.org Product block.

Most retail product pages embed a `<script type="application/ld+json">` Product with an
`offers.availability` value, because that is what Google Shopping reads. It is far
steadier than either a framework's internal state shape or a CSS selector on the buy
button: the markup is a public contract with search engines, so it survives redesigns.

Verified working 2026-09-08 on pokemoncenter.com (product 100-10326), which returns
`availability: http://schema.org/OutOfStock` and `price: 4.49` in the page HTML.

Retailer modules should try this first and keep their bespoke readers as fallbacks.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("tcgwatch.jsonld")

IN_STOCK_RE = re.compile(r"InStock|LimitedAvailability|OnlineOnly|PreOrder", re.I)
OUT_OF_STOCK_RE = re.compile(r"OutOfStock|SoldOut|Discontinued|BackOrder", re.I)

# Collected in the page, not in Python, so one round trip returns every block.
LD_JS = (
    "JSON.stringify([...document.querySelectorAll(\"script[type='application/ld+json']\")]"
    ".map(s => s.textContent))"
)


@dataclass
class Offer:
    in_stock: bool | None
    price: float | None
    availability: str | None   # bare schema.org term, e.g. "OutOfStock"
    name: str | None
    image: str | None

    @property
    def found(self) -> bool:
        return self.in_stock is not None

    @property
    def note(self) -> str:
        return f"json-ld: {self.availability}" if self.found else "json-ld: no offer"


EMPTY = Offer(None, None, None, None, None)


def _first_image(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _first_image(value[0])
    if isinstance(value, dict):
        return _first_image(value.get("url"))
    return None


def _blocks(browser) -> list:
    try:
        raw = browser.eval_json(LD_JS)
    except Exception as e:  # noqa: BLE001 - a browser hiccup is not a stock signal
        log.debug("json-ld eval failed: %s", e)
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return raw or []


def read(browser) -> Offer:
    """First Product offer with an availability value, or EMPTY."""
    for text in _blocks(browser):
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        stack = list(data) if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            offers = item.get("offers")
            if not offers:
                continue
            for offer in (offers if isinstance(offers, list) else [offers]):
                if not isinstance(offer, dict):
                    continue
                availability = str(offer.get("availability") or "")
                if not availability:
                    continue
                if IN_STOCK_RE.search(availability):
                    in_stock = True
                elif OUT_OF_STOCK_RE.search(availability):
                    in_stock = False
                else:
                    log.debug("unrecognised availability %r", availability)
                    continue
                try:
                    price = float(offer["price"]) if offer.get("price") is not None else None
                except (TypeError, ValueError):
                    price = None
                name = item.get("name") if isinstance(item.get("name"), str) else None
                return Offer(in_stock, price, availability.rsplit("/", 1)[-1], name,
                             _first_image(item.get("image")))
    return EMPTY
