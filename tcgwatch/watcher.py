"""Main loop: poll each retailer on its own interval, alert on out-of-stock -> in-stock flips."""

from __future__ import annotations

import logging
import random
import time
import webbrowser

import subprocess
from pathlib import Path

from . import cart as cart_mod
from . import feeds as feeds_mod
from . import grouping
from . import market as market_mod
from . import msrp, notify
from .browser import Browser, BrowserError
from .config import Config
from .retailers import USES_BROWSER, Result, get_checker
from .state import State

log = logging.getLogger("tcgwatch")


class Watcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = State(cfg.data_dir / "state.json")
        self.browser: Browser | None = None
        self.next_due: dict[str, float] = {r: 0.0 for r in cfg.retailers}
        self.feed_due = 0.0
        self.feed_rules = [feeds_mod.FeedRule(f.subreddit, f.keywords, f.exclude) for f in cfg.feeds]
        self.captcha_alerted_at = 0.0
        self.market_due = 0.0
        self.market_paused_until = 0.0
        self.site_dirty = False
        self.site_deployed_at = 0.0

    # -- browser -------------------------------------------------------------------------
    def needs_browser(self) -> bool:
        return self.cfg.cart_mode == "auto" or any(
            r in USES_BROWSER or (r == "bestbuy" and not self.cfg.bestbuy_api_key) for r in self.cfg.retailers
        )

    def get_browser(self) -> Browser | None:
        if self.browser is None and self.needs_browser():
            try:
                self.browser = Browser(self.cfg.chrome_path, self.cfg.profile_dir)
            except BrowserError as e:
                log.error("%s", e)
        return self.browser

    # -- alerts --------------------------------------------------------------------------
    def alert(self, title: str, body: str, url: str | None = None, priority: str = "high", tags: str = "shopping_cart"):
        ok = notify.push(self.cfg, title, body, url, priority, tags)
        log.info("ALERT %s: %s%s", title, body.replace("\n", " | "), "" if ok else " (push failed)")

    def handle(self, res: Result) -> None:
        p = res.product
        prev = self.state.get(p.key)
        was_in = prev.get("in_stock")

        log.info("%-14s %-40s %-6s %s %s", p.retailer, p.name[:40], res.in_stock, f"${res.price:.2f}" if res.price else "", res.note)

        if res.in_stock is None:
            if res.note.startswith("captcha") and time.time() - self.captcha_alerted_at > 1800:
                self.captcha_alerted_at = time.time()
                self.alert("Walmart wants a captcha", "Solve the Robot-or-human check in the watcher's Chrome window.", res.url, "default", "warning")
            self.state.update(p.key, **self._img(res))
            return

        # Alert only on a genuine restock (out of stock -> in stock), never as a "still in stock"
        # reminder. realert_minutes used to re-ping any in-stock item on a timer regardless of
        # whether anything had changed, which pinged @everyone every 30 min forever for a product
        # that never actually sells out (a battle deck sitting at GameStop for hours). A
        # market-price-based deal check didn't reliably fix it either: TCGplayer's cached number
        # can still call a plain at-MSRP item a "deal" even though nothing scarce is happening. If
        # it's still there half an hour later, the first ping already told you (David, 2026-09-07).
        flipped = res.in_stock and not was_in
        if flipped:
            acceptable, label = msrp.verdict(res.price, p.msrp, self.cfg.max_price_ratio)
            carted, opened, landing = False, False, res.url
            if acceptable and p.cart and self.cfg.cart_mode == "auto" and p.retailer != "pokemoncenter":
                b = self.get_browser()
                if b:
                    carted, landing = cart_mod.add_to_cart(b, p)
            elif acceptable and p.cart and self.cfg.cart_mode == "open":
                # Your normal browser, your real profile, no automation signals.
                try:
                    opened = webbrowser.open(res.url, new=2)
                except Exception as e:  # noqa: BLE001
                    log.warning("could not open browser: %s", e)
            if p.retailer == "pokemoncenter":
                body = f"{label}\nJoin the queue / add to cart by hand."
            elif carted:
                body = f"{label}\nIn your cart. Open and press Place Order."
            elif opened:
                body = f"{label}\nOpened on your PC. Add to cart and check out."
            elif not acceptable:
                body = f"{label}\nNot opened. Decide yourself."
            else:
                body = f"{label}\nOpen the link and add to cart."
            self.alert(f"IN STOCK: {p.name}", body, landing, "urgent" if acceptable else "default",
                       "shopping_cart" if acceptable else "money_with_wings")
            self.state.update(p.key, in_stock=True, price=res.price, alerted_at=time.time(), **self._img(res))
            self.site_dirty = True
        else:
            if was_in != res.in_stock or (res.price and res.price != prev.get("price")):
                self.site_dirty = True
            self.state.update(p.key, in_stock=res.in_stock, price=res.price, **self._img(res))

    def _img(self, res: Result) -> dict:
        """Lifecycle fields saved with every result: image, first_seen, last_in_stock, missing_since."""
        prev = self.state.get(res.product.key)
        now = time.time()
        out = {"first_seen": prev.get("first_seen") or now}
        if res.image:
            out["image"] = res.image
        if res.in_stock:
            out["last_in_stock"] = now
        missing = res.in_stock is None and ("missing" in res.note or "404" in res.note or "not in response" in res.note)
        out["missing_since"] = (prev.get("missing_since") or now) if missing else None
        return out

    def record(self, res: Result) -> None:
        """Save a poll result without alerting (used by --once)."""
        fields = self._img(res)
        if res.in_stock is None:
            self.state.update(res.product.key, **fields)
            return
        self.state.update(res.product.key, in_stock=res.in_stock, price=res.price, **fields)

    def active_products(self, retailer: str) -> list:
        """Products still worth polling: not retired."""
        from . import lifecycle

        out = []
        for p in self.cfg.products_for(retailer):
            key = grouping.group_key(p.name)
            siblings = [self.state.get(q.key) for q in self.cfg.products if grouping.group_key(q.name) == key]
            if lifecycle.is_retired(siblings, self.cfg.retire_after_days, self.cfg.retire_missing_days):
                continue
            out.append(p)
        return out

    # -- TCGplayer market prices, one product per tick ------------------------------------
    def run_market_tick(self) -> None:
        if time.time() < self.market_paused_until:
            return
        now = time.time()
        oldest_key, oldest_ts, oldest_name = None, now, ""
        for p in self.cfg.products:
            key = grouping.group_key(p.name)
            ts = self.state.get(f"market:{key}").get("updated", 0.0)
            if ts < oldest_ts:
                oldest_key, oldest_ts, oldest_name = key, ts, p.name
        if oldest_key is None or now - oldest_ts < 86400:
            return
        query = grouping.market_query(oldest_name)
        # A `tcgplayer:` id on any listing in the group pins the lookup to that product.
        pin = next((p.tcgplayer for p in self.cfg.products if p.tcgplayer and grouping.group_key(p.name) == oldest_key), None)
        try:
            hit = market_mod.search(query, grouping.game_of(oldest_name), pin=pin)
        except Exception as e:  # noqa: BLE001
            self.market_paused_until = time.time() + 900
            log.warning("tcgplayer lookup failed (%s); pausing market prices 15 min", e)
            return
        if hit:
            log.info("MARKET %-50s $%s  (%s)", oldest_name[:50], hit["market"], hit["name"][:40])
            self.state.update(f"market:{oldest_key}", query=query, **hit)
        else:
            log.info("MARKET %-50s no match", oldest_name[:50])
            self.state.update(f"market:{oldest_key}", query=query, market=None)
        self.site_dirty = True

    # -- status page ----------------------------------------------------------------------
    def maybe_deploy_site(self) -> None:
        if not (self.cfg.site_deploy and self.site_dirty) or time.time() - self.site_deployed_at < 300:
            return
        from . import site as site_mod

        root = Path(__file__).resolve().parent.parent
        try:
            site_mod.build(self.cfg, root / "site")
            subprocess.Popen(f'npx -y vercel --prod --yes --cwd "{root / "site"}"', shell=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("status page rebuilt and deploy started")
        except Exception as e:  # noqa: BLE001
            log.warning("site deploy failed: %s", e)
        self.site_dirty = False
        self.site_deployed_at = time.time()

    def run_feeds(self, alert: bool = True) -> list[dict]:
        if not self.feed_rules:
            return []
        hits = feeds_mod.check(self.feed_rules, self.state)
        for h in hits:
            price = feeds_mod.price_in(h["title"])
            body = h["title"]
            if price is not None:
                body += f"\n(price in title: ${price:.2f})"
            log.info("FEED r/%s: %s", h["subreddit"], h["title"])
            if alert:
                self.alert(f"r/{h['subreddit']} new post", body, h["url"] or h["permalink"], "high", "newspaper")
        return hits

    # -- loop ----------------------------------------------------------------------------
    def run_retailer(self, retailer: str) -> list[Result]:
        products = self.active_products(retailer)
        browser = self.get_browser() if (retailer in USES_BROWSER or (retailer == "bestbuy" and not self.cfg.bestbuy_api_key)) else None
        try:
            return get_checker(retailer)(products, self.cfg, browser)
        except Exception as e:  # noqa: BLE001
            log.warning("%s check failed: %s", retailer, e)
            return []

    def run_once(self) -> list[Result]:
        out = []
        for r in self.cfg.retailers:
            out.extend(self.run_retailer(r))
        return out

    def run_forever(self) -> None:
        log.info("watching %d products across %s; intervals %s; %d feed rules every %ds",
                 len(self.cfg.products), self.cfg.retailers,
                 {r: self.cfg.intervals[r] for r in self.cfg.retailers}, len(self.feed_rules), self.cfg.feed_interval)
        while True:
            now = time.time()
            for retailer in self.cfg.retailers:
                if now < self.next_due[retailer]:
                    continue
                for res in self.run_retailer(retailer):
                    self.handle(res)
                base = self.cfg.intervals[retailer]
                self.next_due[retailer] = time.time() + base * random.uniform(0.85, 1.15)
            if self.feed_rules and now >= self.feed_due:
                self.run_feeds()
                self.feed_due = time.time() + self.cfg.feed_interval * random.uniform(0.85, 1.15)
            if self.cfg.market and now >= self.market_due:
                self.run_market_tick()
                self.market_due = time.time() + self.cfg.market_interval * random.uniform(0.9, 1.3)
            self.maybe_deploy_site()
            time.sleep(2)
