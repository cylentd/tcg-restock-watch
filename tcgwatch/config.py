"""Load and validate config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_INTERVALS = {"target": 90, "bestbuy": 60, "walmart": 300, "gamestop": 120,
                     "pokemoncenter": 300, "samsclub": 300}


@dataclass
class Product:
    retailer: str
    id: str
    name: str
    msrp: float | None = None
    cart: bool = True
    url: str | None = None
    tcgplayer: int | None = None  # pin the market lookup to this TCGplayer product id

    @property
    def key(self) -> str:
        return f"{self.retailer}:{self.id}"


@dataclass
class Feed:
    subreddit: str
    keywords: list[str]
    exclude: list[str] = field(default_factory=list)


@dataclass
class Config:
    discord_webhook: str | None
    discord_mention_everyone: bool
    ntfy_topic: str | None
    ntfy_server: str
    products: list[Product]
    intervals: dict[str, int]
    max_price_ratio: float
    cart_mode: str  # "open" = open product page in your normal browser; "auto" = controlled-browser add-to-cart; "off"
    chrome_path: str
    profile_dir: str
    bestbuy_api_key: str | None
    zip_code: str
    target_store_id: str
    data_dir: Path
    realert_minutes: int = 30
    feeds: list[Feed] = field(default_factory=list)
    feed_interval: int = 120
    market: bool = True
    market_interval: int = 20
    site_deploy: bool = False
    # Vercel Hobby allows 100 deployments a day and 1 at a time (verified 2026-09-08), so
    # the budget -- not the interval -- is what keeps a churny day from bricking the site.
    # An interval alone cannot: 10-minute spacing sustained all day is 144 deploys.
    site_min_interval: int = 1800    # normal floor between deploys
    site_hot_interval: int = 600     # floor while any watched product is in stock
    site_max_age: int = 1800         # deploy even with nothing changed, to prove liveness
    site_daily_budget: int = 80      # hard stop, leaving headroom under Vercel's 100
    retire_after_days: int = 60
    retire_missing_days: int = 7
    discord_invite: str | None = None
    releases: list[dict] = field(default_factory=list)  # upcoming sets: {game, name, date, note, source}
    # Reddit OAuth app (config.local.yaml). Without it the feeds fall back to the public RSS,
    # which Reddit throttles to almost nothing from a non-browser client.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "windows:tcg-restock-watch:1.0 (personal restock watcher)"

    def products_for(self, retailer: str) -> list[Product]:
        return [p for p in self.products if p.retailer == retailer]

    @property
    def retailers(self) -> list[str]:
        seen: list[str] = []
        for p in self.products:
            if p.retailer not in seen:
                seen.append(p.retailer)
        return seen


def _cart_mode(value) -> str:
    if value is True:
        return "auto"
    if value is False or value is None:
        return "off"
    mode = str(value).lower()
    if mode not in ("open", "auto", "off"):
        raise ValueError(f"cart must be open, auto, or off (got {value!r})")
    return mode


def load(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Secrets (webhook URL, API key) live in config.local.yaml next to config.yaml; it is gitignored.
    local = path.with_name("config.local.yaml")
    if local.exists():
        raw.update(yaml.safe_load(local.read_text(encoding="utf-8")) or {})

    products = []
    for item in raw.get("products", []):
        products.append(
            Product(
                retailer=str(item["retailer"]).lower(),
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                msrp=float(item["msrp"]) if item.get("msrp") is not None else None,
                cart=bool(item.get("cart", True)),
                url=item.get("url"),
                tcgplayer=int(item["tcgplayer"]) if item.get("tcgplayer") else None,
            )
        )

    intervals = dict(DEFAULT_INTERVALS)
    intervals.update({k.lower(): int(v) for k, v in (raw.get("intervals") or {}).items()})

    data_dir = Path(os.path.expanduser(raw.get("data_dir", "~/.tcg-watch")))
    data_dir.mkdir(parents=True, exist_ok=True)

    bb_key = raw.get("bestbuy_api_key") or os.environ.get("BESTBUY_API_KEY") or None

    feeds = [
        Feed(
            subreddit=str(f["subreddit"]),
            keywords=[str(k) for k in f.get("keywords", [])],
            exclude=[str(k) for k in f.get("exclude", [])],
        )
        for f in (raw.get("feeds") or [])
    ]

    webhook = raw.get("discord_webhook") or os.environ.get("DISCORD_WEBHOOK") or None
    topic = raw.get("ntfy_topic") or None
    if topic and "CHANGE-ME" in str(topic):
        topic = None

    return Config(
        discord_webhook=str(webhook) if webhook else None,
        discord_mention_everyone=bool(raw.get("discord_mention_everyone", True)),
        ntfy_topic=str(topic) if topic else None,
        ntfy_server=str(raw.get("ntfy_server", "https://ntfy.sh")).rstrip("/"),
        products=products,
        intervals=intervals,
        max_price_ratio=float(raw.get("max_price_ratio", 1.10)),
        cart_mode=_cart_mode(raw.get("cart", "open")),
        chrome_path=str(raw.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")),
        profile_dir=os.path.expanduser(raw.get("profile_dir", str(data_dir / "chrome-profile"))),
        bestbuy_api_key=bb_key,
        zip_code=str(raw.get("zip_code", "95035")),
        target_store_id=str(raw.get("target_store_id", "626")),
        data_dir=data_dir,
        realert_minutes=int(raw.get("realert_minutes", 30)),
        feeds=feeds,
        feed_interval=int(raw.get("feed_interval", 120)),
        market=bool(raw.get("market", True)),
        market_interval=max(5, int(raw.get("market_interval", 20))),
        site_deploy=bool(raw.get("site_deploy", False)),
        site_min_interval=max(300, int(raw.get("site_min_interval", 1800))),
        site_hot_interval=max(300, int(raw.get("site_hot_interval", 600))),
        site_max_age=max(600, int(raw.get("site_max_age", 1800))),
        site_daily_budget=max(1, min(95, int(raw.get("site_daily_budget", 80)))),
        retire_after_days=int(raw.get("retire_after_days", 60)),
        retire_missing_days=int(raw.get("retire_missing_days", 7)),
        discord_invite=(str(raw["discord_invite"]).strip() or None) if raw.get("discord_invite") else None,
        releases=[dict(r) for r in (raw.get("releases") or []) if isinstance(r, dict)],
        reddit_client_id=(str(raw.get("reddit_client_id") or os.environ.get("REDDIT_CLIENT_ID") or "").strip() or None),
        reddit_client_secret=(str(raw.get("reddit_client_secret") or os.environ.get("REDDIT_CLIENT_SECRET") or "").strip() or None),
        reddit_user_agent=str(raw.get("reddit_user_agent") or "windows:tcg-restock-watch:1.0 (personal restock watcher)"),
    )
