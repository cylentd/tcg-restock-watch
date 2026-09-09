"""Retailer registry. Each module exposes check(products, cfg, browser) -> list[Result]."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Product


@dataclass
class Result:
    product: Product
    in_stock: bool | None  # None = could not determine
    price: float | None
    url: str
    note: str = ""
    image: str | None = None  # product image URL as shown by the retailer


PRODUCT_URLS = {
    "target": "https://www.target.com/p/-/A-{id}",
    "bestbuy": "https://www.bestbuy.com/site/{id}.p?skuId={id}",
    "walmart": "https://www.walmart.com/ip/{id}",
    "gamestop": "https://www.gamestop.com/products/{id}.html",  # 301s to the full product URL
    "pokemoncenter": "https://www.pokemoncenter.com/product/{id}",
    "riotmerch": "https://merch.riotgames.com/en-us/product/{id}/",  # {id} is the URL slug
    # Price-only stub (no product page of its own to check); config should give an explicit
    # `url` per product (e.g. a TCGplayer search link) since {id} here is just an internal key.
    "tcgplayer": "https://www.tcgplayer.com/search/pokemon/product?q={id}",
}

CART_URLS = {
    "target": "https://www.target.com/cart",
    "bestbuy": "https://www.bestbuy.com/cart",
    "walmart": "https://www.walmart.com/cart",
    "gamestop": "https://www.gamestop.com/cart",
    "pokemoncenter": "https://www.pokemoncenter.com/cart",
    "riotmerch": "https://merch.riotgames.com/en-us/cart",
}

# Target's redsky API is called from the browser too: it sits behind Target's bot challenge,
# which a cookieless client from a noticed IP fails on most requests (2026-09-07).
USES_BROWSER = {"target", "walmart", "pokemoncenter"}


def product_url(p: Product) -> str:
    return p.url or PRODUCT_URLS[p.retailer].format(id=p.id)


def get_checker(retailer: str):
    from . import bestbuy, gamestop, pokemoncenter, riotmerch, target, tcgplayer_price, walmart

    return {
        "target": target.check,
        "bestbuy": bestbuy.check,
        "walmart": walmart.check,
        "gamestop": gamestop.check,
        "pokemoncenter": pokemoncenter.check,
        "riotmerch": riotmerch.check,
        "tcgplayer": tcgplayer_price.check,
    }[retailer]
