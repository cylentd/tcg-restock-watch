"""Shared test builders: the Config builder, the fixture loader and the fake browsers.

A fake browser answers with a hand-built payload from tests/fixtures/, so a retailer's parser is
exercised through its public check() without any Chrome, agent-browser or network.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tcgwatch.config import Config
from tcgwatch.watcher import Watcher

FIXTURES = Path(__file__).parent / "fixtures"
WEBHOOK = "https://discord.test/api/webhooks/1/abc"
NTFY_SERVER = "https://ntfy.test"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_config(tmp_path, **overrides) -> Config:
    base = Config(
        discord_webhook=WEBHOOK,
        discord_mention_everyone=True,
        ntfy_topic=None,
        ntfy_server=NTFY_SERVER,
        products=[],
        intervals={},
        max_price_ratio=1.10,
        cart_mode="open",
        chrome_path="",
        profile_dir="",
        bestbuy_api_key=None,
        zip_code="00000",
        target_store_id="1",
        data_dir=tmp_path,
    )
    return dataclasses.replace(base, **overrides)


def make_watcher(tmp_path, **overrides) -> Watcher:
    w = Watcher(make_config(tmp_path, **overrides))
    w.get_browser = lambda: object()  # never launch a real browser
    return w


class WalmartBrowser:
    """Stands in for tcgwatch.browser.Browser as walmart.check uses it: one page, one embedded JSON blob."""

    def __init__(self, next_data: dict):
        self._next_data = next_data

    def open(self, url):
        return None

    def wait(self, ms):
        return None

    def url(self):
        return "https://www.walmart.com/ip/99"

    def title(self):
        return "Pokemon ETB"

    def next_data(self):
        return self._next_data


class TargetBrowser:
    """Stands in for the Browser's fetch_json as target.check uses it: the stock summary, then the price call."""

    def __init__(self, summary: dict, pdp: dict | None = None):
        self.summary = summary
        self.pdp = pdp
        self.endpoints_called: list[str] = []

    def fetch_json(self, url):
        if "product_summary_with_fulfillment_v1" in url:
            self.endpoints_called.append("summary")
            return 200, self.summary, "browser"
        if "pdp_client_v1" in url:
            self.endpoints_called.append("pdp")
            return 200, self.pdp, "browser"
        raise AssertionError(f"unexpected Target endpoint: {url}")


class FakeBrowser:
    """Minimal stand-in for tcgwatch.browser.Browser covering what bestbuy._load()/_browser_check use."""

    def __init__(self, page_info, over_cap_after: int | None = None):
        self.page_info = page_info
        self.over_cap_after = over_cap_after  # recycle should fire once calls reach this count
        self.calls = 0
        self.recycle_calls: list[str] = []
        self.tab_closes = 0

    def run(self, *args, check=True):
        if args[:2] == ("tab", "close"):
            self.tab_closes += 1
        return ""

    def goto(self, url):
        return None

    def wait(self, ms):
        return None

    def eval_json(self, js):
        return self.page_info

    def over_memory_cap(self):
        self.calls += 1
        if self.over_cap_after is not None and self.calls >= self.over_cap_after:
            return "chrome 2001 MB"  # one past the README's 2 GB Chrome cap ("Known limits")
        return None

    def recycle(self, reason):
        self.recycle_calls.append(reason)
        self.over_cap_after = None  # a restarted Chrome starts small, as the real recycle does
