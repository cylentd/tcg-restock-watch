"""Price-only watch for products no retailer sells directly (item 4: booster boxes).

Pokemon (and Riftbound) booster boxes are rarely sold by Target/Best Buy/Walmart/
GameStop themselves -- only bundles, ETBs, and tins are. There is no stock endpoint to
poll for these, so this "retailer" is a stub: every check() call reports
``in_stock=None`` (never determined), which the Watcher already treats as "no alert,
just record it" (see Watcher.handle: `if res.in_stock is None: ... return`, no restock
logic runs). Distinct from a real stock-check retailer: no cart-open, no "IN STOCK"
alert, ever.

The actual price comes from the price tracking that already runs for every product in
config.yaml regardless of retailer: ``tcgwatch/market.py`` (TCGplayer's search endpoint)
via ``Watcher.run_market_tick``, grouped by product name (``tcgwatch/grouping.py``). A
booster box product listed here gets picked up by that existing loop the same as any
other product -- no new TCGplayer client code needed. Pin the exact TCGplayer listing
with `tcgplayer: <product id>` in config.yaml if the name matcher ever picks the wrong
result (same pattern as the existing pinned decks/boxes).

GameNerdz (also named in item 4) is deferred: no probe was run against gamenerdz.com in
this lane (the live TCGplayer poller was already running against the market-price host,
and the host rule is one exploratory host at a time / no bursts on a live-polled host),
so its data shape is unverified. TCGplayer-only ships for v1.
"""

from __future__ import annotations

from ..config import Config, Product
from . import Result, product_url


def check(products: list[Product], cfg: Config, browser=None) -> list[Result]:
    return [
        Result(p, None, None, product_url(p), "price-only: see TCGplayer market price (no stock endpoint)")
        for p in products
    ]
