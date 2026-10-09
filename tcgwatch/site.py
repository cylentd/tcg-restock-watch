"""Generate the static status page (site/index.html) from config.yaml + state.json.

Products are grouped across retailers by normalized name. Each group shows a
thumbnail, MSRP vs TCGplayer market as an inline meter, and the retailer listings
with last-seen price and status. Filtering, search, and sort run client-side.
Mobile first: base styles are the phone layout; 640px and 1024px add columns.

The page is assembled from files, one kind per file (all under tcgwatch/templates/):
structure page.html, style page.css, behaviour page.js, copy copy.json (keyed;
`{{key}}` in html/js), data shops.json. Two extension points let a feature add
files instead of editing this module:
  * templates/sections/<name>.html|css|js  a page section, its style, its script; the html opens
    with `<!-- place: top -->` to sit under the header, else it follows the local shops;
  * site_data/<name>.py  `provide(cfg, state, groups) -> dict`, merged into the page data.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import copy_text, ev, feeds, grouping, history, hotlist, images, lifecycle, site_data, trends
from .config import Config
from .retailers import product_url
from .state import State

RETAILER_LABEL = {"target": "Target", "bestbuy": "Best Buy", "walmart": "Walmart", "gamestop": "GameStop"}
RETAILER_ORDER = {name: rank for rank, name in enumerate(RETAILER_LABEL)}  # listing order inside a row
UNLISTED_RETAILER_RANK = len(RETAILER_ORDER)  # a retailer not named above sorts after the known ones

TEMPLATES = Path(__file__).resolve().parent / "templates"
SECTIONS = TEMPLATES / "sections"
RELEASE_KEEP_DAYS = 14  # a release stays on the calendar this long after its date, as "out now"
SPARK_DAYS = 90  # the sparkline's window
SHORT_TREND_DAYS = 30  # the two % changes the product sheet shows
LONG_TREND_DAYS = 90
MIN_HISTORY_ROWS = 2  # a trend needs at least two recorded days
PREMIUM_DIGITS = 2

# One local-shop card. Structure, so it lives here beside the loop that fills it; the shops are data.
SHOP_CARD = ('<a class="lgs-card" href="{url}" target="_blank" rel="noopener">'
             '<span class="lgs-name">{name}</span><span class="lgs-city">{city}</span></a>')
SHOP_JOIN = "\n    "  # the cards sit in page.html at the grid's indent
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
PLACE_MARKER = re.compile(r"\A<!-- place: (\w+) -->\n?")
SECTION_PLACES = ("top",)  # a section with no marker follows the local shops; "top" sits under the header


def _status(entry: dict) -> str:
    if not entry:
        return "unknown"
    if entry.get("in_stock"):
        return "in"
    if entry.get("in_stock") is False:
        return "out"
    return "unknown"


def _group_listings(cfg: Config, state: State) -> tuple[dict[str, dict], float]:
    """Group the configured products across retailers; also the newest poll time seen."""
    groups: dict[str, dict] = {}
    last_poll = 0.0
    for p in cfg.products:
        if not hotlist.is_hot(p.name, p.hot):
            continue  # README "Hot items": only hot products are shown
        key = grouping.group_key(p.name)
        g = groups.setdefault(
            key,
            {"key": key, "game": grouping.game_of(p.name), "name": grouping.display_name(p.name), "msrp": None,
             "market": None, "listings": []},
        )
        if g["msrp"] is None and p.msrp:
            g["msrp"] = p.msrp
        entry = state.get(p.key)
        last_poll = max(last_poll, entry.get("updated", 0.0))
        g["listings"].append(
            {
                "retailer": p.retailer,
                "price": entry.get("price"),
                "status": _status(entry),
                "checked": entry.get("updated"),
                "url": product_url(p),
                "image": entry.get("image"),
                "_entry": entry,
            }
        )
    return groups, last_poll


def _history_block(cfg: Config, key: str) -> dict | None:
    """30/90-day price trend (roadmap item 3), only once enough daily rows exist to say anything
    (see tcgwatch/history.py, appended once a day by the watcher's market tick)."""
    series = history.series_for(cfg.data_dir, key)
    if len(series) < MIN_HISTORY_ROWS:
        return None
    return {
        "pct30": history.change_pct(series, SHORT_TREND_DAYS),
        "pct90": history.change_pct(series, LONG_TREND_DAYS),
        "spark": history.sparkline_points(series, SPARK_DAYS),
    }


def _attach_image(g: dict, m: dict | None, img_dir: Path | None) -> None:
    src = next((l["image"] for l in g["listings"] if l.get("image")), None) or (
        images.tcgplayer_image(m.get("product_id")) if m and m.get("product_id") else None
    )
    webp = images.ensure_webp(src, img_dir) if (src and img_dir is not None) else None
    g["img"] = f"img/{webp}" if webp else None
    for l in g["listings"]:
        l.pop("image", None)


def _enrich(g: dict, cfg: Config, state: State, titles: list, img_dir: Path | None) -> None:
    """Fill one group's derived fields: lifecycle, market, image, hot score, EV, trend."""
    key = g["key"]
    entries = [l.pop("_entry") for l in g["listings"]]
    g["retired"] = lifecycle.is_retired(entries, cfg.retire_after_days, cfg.retire_missing_days)
    g["last_in_stock"] = max((e.get("last_in_stock") or 0.0) for e in entries) or None
    g["buzz"] = lifecycle.buzz(g["name"], titles)
    g["kind"] = lifecycle.product_kind(g["name"])
    m = state.get(f"market:{key}")
    if m and m.get("market") is not None:
        g["market"] = {"price": m["market"], "url": m.get("url"), "name": m.get("name")}
    _attach_image(g, m, img_dir)
    g["in_stock"] = any(l["status"] == "in" for l in g["listings"])
    g["premium"] = round(g["market"]["price"] / g["msrp"], PREMIUM_DIGITS) if g["market"] and g["msrp"] else None
    g["hot"] = lifecycle.hot_score(g["premium"], g["buzz"], g["last_in_stock"], g["in_stock"], g["name"])
    # Chase-card EV, only for the handful of sets with pull-rate data (data/pull_rates.yaml).
    # box_price prefers the live market price (what it actually costs to buy right now) over
    # MSRP, since the question is "worth buying at today's price", not at list price.
    set_key = ev.match_group(g["name"])
    box_price = (g["market"]["price"] if g["market"] else None) or g["msrp"]
    g["ev"] = ev.get_or_refresh(state, set_key, box_price) if set_key else None
    g["history"] = _history_block(cfg, key)
    g["listings"].sort(key=lambda l: RETAILER_ORDER.get(l["retailer"], UNLISTED_RETAILER_RANK))


def collect(cfg: Config, img_dir: Path | None = None) -> dict:
    state = State(cfg.data_dir / "state.json")
    groups, last_poll = _group_listings(cfg, state)
    titles = feeds.recent_titles(state, [f.subreddit for f in cfg.feeds])
    for g in groups.values():
        _enrich(g, cfg, state, titles, img_dir)
    ordered = sorted(groups.values(), key=lambda g: (bool(g["retired"]), -g["hot"], g["name"].lower()))
    data = {
        "generated": time.time(),
        "generated_label": datetime.now().strftime("%b %d, %H:%M"),
        "last_poll": last_poll,
        "releases": _releases(cfg),
        "groups": ordered,
        "feeds": [f"r/{f.subreddit}" for f in cfg.feeds],
        "buzz_posts": len(titles),
        "discord_invite": cfg.discord_invite,
    }
    data.update(site_data.provide_all(cfg, state, ordered, reserved=data.keys()))
    return data


def _releases(cfg: Config) -> list[dict]:
    """Upcoming releases from config, dated, sorted; keeps the last 14 days as 'out now'."""
    today = datetime.now().date()
    out = []
    for r in cfg.releases:
        try:
            d = datetime.strptime(str(r.get("date", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (d - today).days
        if days < -RELEASE_KEEP_DAYS:
            continue
        out.append({
            "game": r.get("game", ""), "name": r.get("name", ""), "date": d.isoformat(),
            "mon": d.strftime("%b"), "day": d.day, "days": days,
            "note": r.get("note", ""), "source": r.get("source"),
        })
    out.sort(key=lambda r: r["date"])
    return out


# -- assembling the page from templates/ -----------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fill(text: str, ctx: dict[str, str]) -> str:
    """Replace each {{key}} from ctx in one pass; a key with no value fails the build."""
    def pick(m: re.Match) -> str:
        if m.group(1) not in ctx:
            raise KeyError(f"template placeholder {{{{{m.group(1)}}}}} has no value (copy.json or a section)")
        return ctx[m.group(1)]
    return PLACEHOLDER.sub(pick, text)


def _shop_cards(shops: list[dict]) -> str:
    return SHOP_JOIN.join(
        SHOP_CARD.format(url=html.escape(s["url"]), name=html.escape(s["name"]), city=html.escape(s["city"]))
        for s in shops
    )


def _section_parts(directory: Path) -> dict[str, list[str]]:
    """Every section's html, css and js, in name order. A section may have any of the three."""
    parts: dict[str, list[str]] = {"html": [], "top": [], "css": [], "js": []}
    names = sorted({p.stem for p in directory.glob("*") if p.suffix in (".html", ".css", ".js")}) if directory.is_dir() else []
    for name in names:
        for kind in ("html", "css", "js"):
            f = directory / f"{name}.{kind}"
            if not f.is_file():
                continue
            text = _read(f)
            if kind == "html":
                place, text = _split_place(f.name, text)
                kind = place or "html"
            parts[kind].append(text)
    return parts


def _split_place(filename: str, text: str) -> tuple[str | None, str]:
    """A section's html may open with `<!-- place: top -->`; returns (place, html without the marker)."""
    m = PLACE_MARKER.match(text)
    if not m:
        return None, text
    if m.group(1) not in SECTION_PLACES:
        raise ValueError(f"{filename}: unknown place {m.group(1)!r} (known: {', '.join(SECTION_PLACES)})")
    return m.group(1), text[m.end():]


def _with_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def copy_context() -> dict[str, str]:
    """Every copy key, with the numbers the rules own filled in.

    `{{window_days}}` in a copy value is the trends window (trends.WINDOW_DAYS), so the wording never
    repeats a number that lives in code. It is also a key of its own for the page templates.
    """
    derived = {"window_days": str(trends.WINDOW_DAYS)}
    return {**{key: _fill(text, derived) for key, text in copy_text.load().items()}, **derived}


def render(data: dict) -> str:
    """The page for this data: page.html with style, script, copy, shops and sections filled in."""
    sections = _section_parts(SECTIONS)
    ctx = {**copy_context(), "shops": _shop_cards(json.loads(_read(TEMPLATES / "shops.json")))}
    for key in ("html", "top"):
        ctx[f"sections_{key}"] = _fill("".join("\n" + h.rstrip("\n") for h in sections[key]), ctx)
    style = _fill("".join(_with_newline(c) for c in [_read(TEMPLATES / "page.css"), *sections["css"]]), ctx)
    script = _fill("".join(_with_newline(j) for j in [_read(TEMPLATES / "page.js"), *sections["js"]]), ctx)
    page = _fill(_read(TEMPLATES / "page.html"), ctx)
    page = page.replace("__STYLE__", style).replace("__SCRIPT__", script)
    return page.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))


def build(cfg: Config, out_dir: Path) -> Path:
    data = collect(cfg, out_dir / "img")
    root = Path(__file__).resolve().parent.parent
    data["mascot"] = images.export_mascot(root / "assets" / "mascot.png", out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(render(data), encoding="utf-8")
    (out_dir / "vercel.json").write_text(json.dumps({"cleanUrls": True}), encoding="utf-8")
    return out
