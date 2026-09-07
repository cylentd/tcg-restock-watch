"""Generate the static status page (site/index.html) from config.yaml + state.json.

Products are grouped across retailers by normalized name. Each group shows a
thumbnail, MSRP vs TCGplayer market as an inline meter, and the retailer listings
with last-seen price and status. Filtering, search, and sort run client-side.
Mobile first: base styles are the phone layout; 640px and 1024px add columns.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import feeds, grouping, images, lifecycle
from .config import Config
from .retailers import product_url
from .state import State

RETAILER_LABEL = {"target": "Target", "bestbuy": "Best Buy", "walmart": "Walmart", "gamestop": "GameStop"}


def _status(entry: dict) -> str:
    if not entry:
        return "unknown"
    if entry.get("in_stock"):
        return "in"
    if entry.get("in_stock") is False:
        return "out"
    return "unknown"


def collect(cfg: Config, img_dir: Path | None = None) -> dict:
    state = State(cfg.data_dir / "state.json")
    groups: dict[str, dict] = {}
    last_poll = 0.0
    for p in cfg.products:
        key = grouping.group_key(p.name)
        g = groups.setdefault(
            key,
            {"key": key, "game": grouping.game_of(p.name), "name": grouping.market_query(p.name), "msrp": None,
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
    order = {"target": 0, "bestbuy": 1, "walmart": 2, "gamestop": 3}
    titles = feeds.recent_titles(state, [f.subreddit for f in cfg.feeds])
    for key, g in groups.items():
        entries = [l.pop("_entry") for l in g["listings"]]
        g["retired"] = lifecycle.is_retired(entries, cfg.retire_after_days, cfg.retire_missing_days)
        g["last_in_stock"] = max((e.get("last_in_stock") or 0.0) for e in entries) or None
        g["buzz"] = lifecycle.buzz(g["name"], titles)
        g["kind"] = lifecycle.product_kind(g["name"])
        m = state.get(f"market:{key}")
        if m and m.get("market") is not None:
            g["market"] = {"price": m["market"], "url": m.get("url"), "name": m.get("name")}
        src = next((l["image"] for l in g["listings"] if l.get("image")), None) or (
            images.tcgplayer_image(m.get("product_id")) if m and m.get("product_id") else None
        )
        webp = images.ensure_webp(src, img_dir) if (src and img_dir is not None) else None
        g["img"] = f"img/{webp}" if webp else None
        for l in g["listings"]:
            l.pop("image", None)
        g["in_stock"] = any(l["status"] == "in" for l in g["listings"])
        g["premium"] = round(g["market"]["price"] / g["msrp"], 2) if g["market"] and g["msrp"] else None
        g["hot"] = lifecycle.hot_score(g["premium"], g["buzz"], g["last_in_stock"], g["in_stock"], g["name"])
        g["listings"].sort(key=lambda l: order.get(l["retailer"], 9))
    return {
        "generated": time.time(),
        "generated_label": datetime.now().strftime("%b %d, %H:%M"),
        "last_poll": last_poll,
        "releases": _releases(cfg),
        "groups": sorted(groups.values(), key=lambda g: (bool(g["retired"]), -g["hot"], g["name"].lower())),
        "feeds": [f"r/{f.subreddit}" for f in cfg.feeds],
        "buzz_posts": len(titles),
        "discord_invite": cfg.discord_invite,
    }


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
        if days < -14:
            continue
        out.append({
            "game": r.get("game", ""), "name": r.get("name", ""), "date": d.isoformat(),
            "mon": d.strftime("%b"), "day": d.day, "days": days,
            "note": r.get("note", ""), "source": r.get("source"),
        })
    out.sort(key=lambda r: r["date"])
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0f1f">
<title>Restock Watch</title>
<link rel="icon" type="image/png" href="icon.png">
<link rel="apple-touch-icon" href="icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    /* Night launch: navy sky, flame amber accent, cream ink. Status hues stay reserved. */
    --canvas:#0b0f1f; --card:rgba(255,255,255,.045); --card-2:rgba(255,255,255,.08); --line:rgba(255,255,255,.10); --line-2:rgba(255,255,255,.17);
    --glass:rgba(255,255,255,.05); --stroke:rgba(255,255,255,.10);
    --ink:#f6f1e6; --ink-2:#c9c8dc; --ink-3:#8f90ad;
    --good:#0ca30c; --warn:#fab219; --accent:#f2b134; --accent-2:#ff5a4e; --sky:#7cd4ff;
    --target:#ff5a4e; --bestbuy:#ffd83b; --walmart:#5aa9ff; --gamestop:#c084fc;
    --display:'Bricolage Grotesque','Source Sans 3',sans-serif;
    --body:'Source Sans 3','Segoe UI',system-ui,sans-serif;
  }
  * { box-sizing:border-box; }
  html { background:var(--canvas); -webkit-text-size-adjust:100%; color-scheme:dark; }
  body { margin:0; color:var(--ink); font:15px/1.4 var(--body); min-height:100vh;
    background:
      radial-gradient(900px 520px at 85% -8%, rgba(242,177,52,.16), transparent 62%),
      radial-gradient(700px 480px at -10% 8%, rgba(124,212,255,.12), transparent 60%),
      radial-gradient(1200px 800px at 50% 110%, rgba(255,90,78,.10), transparent 60%),
      linear-gradient(180deg, #0d1226 0%, var(--canvas) 45%, #090c19 100%);
    padding-left:env(safe-area-inset-left); padding-right:env(safe-area-inset-right); padding-bottom:max(24px, env(safe-area-inset-bottom)); }
  /* No starfield: 1px dots on navy read as dead pixels (removed 2026-09-07). The gradients carry the sky. */
  .wrap { position:relative; z-index:1; }
  body::after { content:""; position:fixed; top:0; left:0; right:0; height:2px; z-index:6; background:color-mix(in srgb, var(--accent) 60%, transparent); opacity:.6; }
  @keyframes rise { from { opacity:0; transform:translateY(14px);} }
  header, .stats, .reel-wrap, .cal-wrap, .bar, .list { animation:rise .45s cubic-bezier(.2,.7,.2,1) both; }
  .stats { animation-delay:.05s; } .reel-wrap { animation-delay:.1s; } .cal-wrap { animation-delay:.12s; } .bar { animation-delay:.15s; } .list { animation-delay:.2s; }

  /* Coming up: a row of vertical tiles, tall not wide. The glyph is the dominant visual (the
     game reads at a glance before the name does); date leaf and countdown book-end it. */
  .cal-wrap { margin:16px -16px 0; }
  .cal-wrap .reel-head { padding:0 16px 8px; }
  .cal { display:flex; gap:10px; overflow-x:auto; scroll-snap-type:x proximity; padding:4px 16px 12px; scrollbar-width:none; align-items:stretch;
    -webkit-mask-image:linear-gradient(90deg, #000 calc(100% - 28px), transparent); mask-image:linear-gradient(90deg, #000 calc(100% - 28px), transparent); }
  .cal::-webkit-scrollbar { display:none; }
  .cal { cursor:grab; user-select:none; -webkit-user-select:none; } .cal.drag { cursor:grabbing; scroll-snap-type:none; }
  /* Neutral card, matching every other card on the page (rows, tiles, sheet) — color is an accent,
     not a fill. The corner glyph alone carries game identity; a colored card border here collided
     with the urgency color on the countdown line below (David, 2026-09-07). */
  .rel { position:relative; flex:none; width:132px; scroll-snap-align:start; display:flex; flex-direction:column; padding:13px 12px 12px; border-radius:14px;
    background:var(--card-2); border:1px solid var(--stroke); text-decoration:none; color:inherit; transition:transform .2s, border-color .2s; }
  a.rel:hover { transform:translateY(-3px); border-color:var(--line-2); }
  .rel-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:11px; }
  .rel .date-mon { font:800 12px/1 var(--body); letter-spacing:.09em; text-transform:uppercase; color:var(--ink-3); }
  .rel .date-day { font:800 27px/1 var(--display); color:var(--ink); letter-spacing:-.02em; margin-top:3px; }
  .rel.soon .date-day { color:#ff8a80; } .rel.near .date-day { color:var(--warn); } .rel.now { opacity:.75; }
  .rel-icon { flex:none; width:30px; height:30px; border-radius:9px; display:grid; place-items:center;
    background:color-mix(in srgb, var(--gc) 26%, transparent); color:var(--gc); }
  .rel-icon svg { width:17px; height:17px; }
  .rel-n { font:700 14px/1.25 var(--display); letter-spacing:-.01em; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:auto; }
  .rel-when { font:700 10px/1 var(--body); letter-spacing:.04em; color:var(--ink-3); margin-top:12px; padding-top:10px; border-top:1px solid var(--line); }
  .rel.soon .rel-when { color:#ff8a80; border-top-color:rgba(255,90,78,.35); }
  .rel.near .rel-when { color:var(--warn); border-top-color:rgba(250,178,25,.3); }
  .rel.now .rel-when { color:#5fd65f; }
  .gi { display:inline-flex; width:14px; height:14px; color:var(--gc, currentColor); vertical-align:-2px; margin-right:5px; }
  .gi svg { width:100%; height:100%; }

  /* Game badges: one glyph per game, hue on the glyph only (retailers own the dot colors). */
  .tag { display:inline-flex; align-items:center; gap:4px; }
  .tag svg { width:11px; height:11px; color:var(--gc, currentColor); flex:none; }
  .seg button svg { width:12px; height:12px; color:var(--gc, currentColor); }
  .seg button.on svg { color:inherit; }

  /* Hot reel: drifting, draggable strip of the hottest packshots */
  .reel-wrap { margin:16px -16px 0; }
  .reel-head { display:flex; align-items:baseline; gap:10px; padding:0 16px 8px; }
  /* "Coming up" collapses to this one line on return visits — with 100+ products below, the
     bottom of the page is never reached, so hiding the calendar there would bury it just as
     badly; staying compact at the top keeps it seen without adding scroll (David, 2026-09-07). */
  .cal-toggle { width:100%; border:0; background:none; color:inherit; text-align:left; cursor:pointer; font:inherit; border-radius:10px;
    transition:background .15s, transform .12s; }
  .cal-toggle:hover { background:var(--glass); }
  .cal-toggle:active { transform:scale(.98); }
  .cal-toggle .chev { width:13px; height:13px; margin-left:auto; color:var(--ink-3); transition:transform .35s cubic-bezier(.16,1,.3,1), color .15s; flex:none; }
  .cal-toggle:hover .chev { color:var(--accent); }
  .cal-wrap.collapsed .cal-toggle .chev { transform:rotate(-90deg); }
  /* grid-template-rows 1fr<->0fr animates smoothly where display:none/height:auto can't; the
     inner .cal needs min-height:0 or a 0fr track can't actually squeeze it shut
     (David: "make it more aesthetic to close and open", 2026-09-07). */
  .cal-collapse { display:grid; grid-template-rows:1fr; transition:grid-template-rows .45s cubic-bezier(.16,1,.3,1); }
  .cal-collapse .cal { min-height:0; transition:opacity .45s cubic-bezier(.16,1,.3,1), transform .45s cubic-bezier(.16,1,.3,1); }
  .cal-wrap.collapsed .cal-collapse { grid-template-rows:0fr; }
  .cal-wrap.collapsed .cal-collapse .cal { opacity:0; transform:translateY(-8px); }
  .reel-head .micro { color:var(--accent); }
  .reel { overflow:hidden; cursor:grab; user-select:none; -webkit-user-select:none; touch-action:pan-y;
    -webkit-mask-image:linear-gradient(90deg, transparent, #000 6%, #000 92%, transparent); mask-image:linear-gradient(90deg, transparent, #000 6%, #000 92%, transparent); }
  .reel.drag { cursor:grabbing; }
  .track { display:flex; gap:10px; width:max-content; padding:6px 16px 14px; will-change:transform; }
  .tile { flex:none; width:150px; border-radius:16px; background:var(--card-2); border:1px solid var(--stroke); padding:12px 12px 10px; text-decoration:none; color:inherit;
    display:flex; flex-direction:column; gap:8px; transition:transform .2s, border-color .2s, box-shadow .2s; }
  .tile:hover { transform:translateY(-6px) scale(1.02); border-color:color-mix(in srgb, var(--accent) 55%, var(--stroke)); box-shadow:0 18px 40px -14px rgba(0,0,0,.7); }
  .tile.in { border-color:#5fd65f; box-shadow:0 0 0 1px #5fd65f33, 0 0 24px #5fd65f22; }
  .tile.in:hover { border-color:#5fd65f; box-shadow:0 0 0 1px #5fd65f33, 0 0 24px #5fd65f22, 0 18px 40px -14px rgba(0,0,0,.7); }
  .tile .art { position:relative; height:118px; width:100%; flex:none; }
  .tile .art img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; display:block; filter:drop-shadow(0 10px 16px rgba(0,0,0,.6)); transition:transform .25s; }
  .tile .art svg { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); }
  .tile:hover .art img { transform:scale(1.06) rotate(-2deg); }
  .tile .art svg { width:26px; height:26px; color:var(--ink-3); }
  .tile .t { font:700 13px/1.2 var(--display); letter-spacing:-.01em; min-height:2.4em; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
  .tile .x { display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--ink-2); }
  .tile .x b { color:var(--ink); font-size:15px; margin-left:auto; }
  .tile .x .in { color:#5fd65f; font-weight:700; font-size:11px; letter-spacing:.06em; text-transform:uppercase; }
  a { color:inherit; }
  .wrap { max-width:42rem; margin:0 auto; padding:0 16px; }
  .micro { font:700 11px/1 var(--body); letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3); }
  .num { font-variant-numeric:tabular-nums; }

  header { padding:22px 0 10px; }
  .hero { display:flex; align-items:center; gap:12px; }
  .hero > div { min-width:0; flex:1; }
  .mascot { width:auto; height:76px; flex:none; margin-left:-4px; filter:drop-shadow(0 12px 22px rgba(0,0,0,.55)) drop-shadow(0 0 28px rgba(242,177,52,.28)); animation:hover 4s ease-in-out infinite; }
  @keyframes hover { 0%,100% { transform:translateY(0) rotate(-2deg);} 50% { transform:translateY(-6px) rotate(2deg);} }
  @media (prefers-reduced-motion:reduce) { .mascot { animation:none; } }
  h1 { font:800 30px/1 var(--display); letter-spacing:-.02em; margin:0 0 8px; text-wrap:balance; }
  h1 em { font-style:normal; color:var(--accent); }
  .sub { color:var(--ink-2); margin:0; font-size:14px; }
  .join { display:inline-flex; align-items:center; gap:8px; margin-top:12px; padding:0 14px; min-height:40px; border-radius:10px; text-decoration:none;
    background:#5865F2; color:#fff; font:700 13px/1 var(--body); box-shadow:0 10px 24px -12px rgba(88,101,242,.9); transition:transform .12s, filter .12s; }
  .join[hidden] { display:none; }
  .join svg { width:18px; height:18px; }
  .join:hover { transform:translateY(-1px); filter:brightness(1.08); }

  .stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:14px 0 0; }
  .stat { background:var(--glass); border:1px solid var(--stroke); border-radius:14px; padding:12px 12px 10px; min-height:64px; }
  .stat .v { font:600 26px/1 var(--body); color:var(--ink); display:flex; align-items:center; gap:8px; }
  .stat .v .dot { width:9px; height:9px; border-radius:50%; background:var(--good); box-shadow:0 0 0 3px rgba(12,163,12,.22); }
  .stat .l { color:var(--ink-3); font-size:12px; margin-top:5px; line-height:1.25; }

  .bar { position:sticky; top:0; z-index:5; margin:12px -16px 12px; padding:8px 16px 10px; background:rgba(11,15,31,.88); backdrop-filter:blur(12px); border-bottom:1px solid var(--line); }
  .search { display:flex; align-items:center; gap:8px; background:var(--glass); border:1px solid var(--line-2); border-radius:10px; padding:0 12px; min-height:40px; }
  .search input[type=search]::-webkit-search-cancel-button { filter:invert(.8); }
  .search input { flex:1; background:none; border:0; outline:0; color:var(--ink); font:16px var(--body); min-width:0; }
  .search input::placeholder { color:var(--ink-3); }
  .strip { display:flex; gap:6px; flex-wrap:nowrap; overflow-x:auto; margin:8px -16px 0; padding:0 16px; scrollbar-width:none;
    -webkit-mask-image:linear-gradient(to right, #000 calc(100% - 28px), transparent); mask-image:linear-gradient(to right, #000 calc(100% - 28px), transparent); }
  .strip::-webkit-scrollbar { display:none; }
  .seg { display:inline-flex; gap:2px; background:var(--card); border:1px solid var(--line-2); border-radius:9px; padding:2px; flex:none; }
  .seg button, .chip, .sortsel { cursor:pointer; border:0; background:transparent; color:var(--ink-2); font:700 12px/1 var(--body); padding:0 10px; min-height:32px; border-radius:7px;
    display:inline-flex; align-items:center; gap:6px; white-space:nowrap; position:relative; }
  .seg button.on { background:var(--accent); color:#1a1203; }
  .chip { flex:none; border:1px solid var(--line-2); background:var(--card); border-radius:9px; }
  .chip .sw { width:8px; height:8px; border-radius:50%; background:var(--c); opacity:.4; }
  .chip.on { border-color:var(--line-2); color:var(--ink); background:var(--card-2); }
  .chip.on .sw { opacity:1; }
  /* color-scheme:dark tells the browser to render the native options POPUP (not reachable by
     normal CSS) in dark colors instead of its default bright-white; the explicit option colors
     reinforce it on Chromium, which honors background/color on <option> directly
     (David: "the dropdown container is ugly. It's bright white background", 2026-09-07). */
  .sortsel { border:0; background:transparent; flex:none; appearance:none; -webkit-appearance:none; color:var(--ink-2); font:700 12px/1 var(--body);
    padding:0 20px 0 5px; min-height:30px; color-scheme:dark; }
  .sortsel option { background:#181d36; color:var(--ink); }
  .selwrap { position:relative; display:inline-flex; align-items:center; flex:none; border:1px solid var(--line-2); background:var(--card);
    border-radius:9px; padding-left:9px; min-height:32px; transition:border-color .15s, background .15s; }
  .selwrap:hover { background:var(--card-2); border-color:var(--line-2); }
  .selwrap .si { width:13px; height:13px; color:var(--ink-3); flex:none; }
  .selwrap .chev { position:absolute; right:8px; top:50%; transform:translateY(-50%); width:11px; height:11px; color:var(--ink-3); pointer-events:none; }
  .selwrap.active { border-color:color-mix(in srgb, var(--accent) 60%, var(--line-2)); background:color-mix(in srgb, var(--accent) 12%, var(--card)); }
  .selwrap.active .si { color:var(--accent); }
  .selwrap.active .sortsel { color:var(--ink); }
  .count { color:var(--ink-3); font-size:12px; margin-top:8px; }

  .list { display:flex; flex-direction:column; gap:8px; }
  .row { background:var(--glass); border:1px solid var(--stroke); border-radius:16px; padding:12px; display:grid; grid-template-columns:76px minmax(0,1fr); gap:10px 12px; align-items:start;
    transition:transform .2s, border-color .2s, box-shadow .2s, background .2s; }
  .row:hover { transform:translateY(-2px); background:var(--card-2); border-color:var(--line-2); box-shadow:0 18px 40px -18px rgba(0,0,0,.75); }
  .row.in { border-color:rgba(12,163,12,.6); box-shadow:0 0 0 1px rgba(12,163,12,.25), 0 16px 40px -20px rgba(12,163,12,.6); }
  .thumb { position:relative; width:76px; height:76px; border-radius:10px; display:grid; place-items:center; overflow:visible; flex:none; }
  .thumb img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; display:block; filter:drop-shadow(0 8px 14px rgba(0,0,0,.6)) drop-shadow(0 0 1px rgba(255,255,255,.25)); transition:transform .2s; }
  .row:hover .thumb img { transform:scale(1.06) rotate(-2deg); }
  .thumb:has(svg) { background:var(--card-2); border:1px solid var(--line); }
  .thumb svg { width:30px; height:30px; color:#9a94a8; }
  .head { min-width:0; }
  .name { font:700 16px/1.2 var(--display); letter-spacing:-.01em; cursor:pointer;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.4em; }
  .name:hover { text-decoration:underline; text-decoration-color:var(--line-2); text-underline-offset:3px; }
  .toast { position:fixed; left:50%; bottom:24px; transform:translateX(-50%) translateY(8px); z-index:20; max-width:calc(100vw - 32px);
    background:var(--card-2); border:1px solid var(--line-2); color:var(--ink); font:700 13px/1 var(--body); padding:10px 16px; border-radius:10px;
    opacity:0; pointer-events:none; transition:opacity .2s, transform .2s; box-shadow:0 12px 30px -10px rgba(0,0,0,.6); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
  .meta { display:flex; gap:6px; align-items:center; margin-top:5px; flex-wrap:wrap; }
  .tag { font:700 10px/1 var(--body); letter-spacing:.08em; text-transform:uppercase; padding:4px 6px; border-radius:5px; border:1px solid var(--line-2); color:var(--ink-2); }
  .meter { grid-column:1 / -1; display:flex; flex-direction:column; gap:5px; }
  .cmp-head { display:flex; align-items:baseline; gap:8px; margin-bottom:2px; }
  .cmp-head b { font:700 22px/1 var(--body); color:var(--ink); }
  .cmp-head span { font-size:12px; color:var(--ink-2); }
  .cmp-head.muted span { color:var(--ink-3); }
  .cmp-head.ok b, .cmp-head.ok span { color:#5fd65f; }
  .cmp-head.hi b, .cmp-head.hi span { color:var(--warn); }
  .cmp-head.wild b, .cmp-head.wild span { color:#ff8a80; }
  .cmp-row { display:grid; grid-template-columns:56px minmax(0,1fr) 62px; align-items:center; gap:8px; }
  .cmp-l { font:700 10px/1 var(--body); letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3); }
  .cmp-t { display:block; height:10px; border-radius:2px 5px 5px 2px; background:rgba(255,255,255,.04); }
  .cmp-b { display:block; height:100%; border-radius:2px 5px 5px 2px; }
  .cmp-b.msrp { background:var(--sky); }
  .cmp-b.mkt { background:linear-gradient(90deg, var(--accent), var(--accent-2)); }
  /* Severity moves onto the Market bar's own color (green/amber/red) once the row dropped the
     "3.0x over MSRP" readout — the bar carries magnitude (length) and severity (color) on its
     own, nothing else to read (David, 2026-09-07). */
  .cmp-b.mkt.ok { background:#5fd65f; }
  .cmp-b.mkt.hi { background:var(--warn); }
  .cmp-b.mkt.wild { background:#ff8a78; }
  .cmp-v { font-size:13px; font-weight:700; color:var(--ink); text-align:right; white-space:nowrap; }
  /* Retailer cards: fixed two-line layout in a uniform grid, so five products with different
     numbers of listings, and listings with/without a deal verdict, still line up cleanly instead
     of wrapping into ragged, differently-sized pills (David: "they don't look good", 2026-09-07). */
  /* 1fr keeps the auto-fit column-count math based on the 190px floor, so multi-listing rows
     still wrap into the right number of columns; max-width on the card itself (not the track)
     stops a lone card from stretching across a wide row and leaving a dead gap next to the
     status pill — the track can be wide, the card inside it doesn't have to be (David, 2026-09-07). */
  .shops { grid-column:1 / -1; display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:6px; }
  .shop { text-decoration:none; display:flex; flex-direction:column; gap:4px; padding:7px 9px; border-radius:11px; max-width:250px; justify-self:start;
    background:var(--card-2); border:1px solid var(--line); font-size:13px; color:var(--ink-2); transition:border-color .15s, background .15s, transform .15s; }
  .shop:hover { border-color:var(--line-2); background:var(--card); transform:translateY(-2px); }
  /* fit-content sizing let a long combo (name + price + deal badge + status) overflow the row's
     own edge — capping at 100% of the grid cell and letting the pill wrap its own children onto
     a second line, instead of spilling out, keeps the name intact without ever breaking layout
     (David: "still a problem, its overflowing", 2026-09-07). */
  .shop.solo { flex-direction:row; flex-wrap:wrap; align-items:center; gap:5px 7px; min-height:34px; max-width:100%; width:fit-content; padding:6px 10px; row-gap:2px; }
  /* .shop .r's flex:1 + min-width:0 exist so the name can shrink with an ellipsis inside a
     multi-card row; inside a fit-content solo pill they instead let the flex/shrink-to-fit sizing
     pass compress the name below its own text width, truncating "GameStop" for no reason — solo
     has nothing to shrink for, so give the name its natural width back (2026-09-07). */
  .shop.solo .r { flex:none; overflow:visible; text-overflow:clip; }
  .shop.more { flex-direction:row; align-items:center; justify-content:center; min-height:34px; max-width:none; width:fit-content; padding:0 14px;
    font:700 12px/1 var(--body); color:var(--ink-2); cursor:pointer; appearance:none; -webkit-appearance:none; }
  .shop.more:hover { color:var(--ink); background:var(--card); border-color:var(--line-2); }
  .shop-top { display:flex; align-items:center; gap:6px; min-width:0; }
  .shop .id { width:7px; height:7px; border-radius:50%; background:var(--c); flex:none; }
  .shop .r { font-weight:700; color:var(--ink); flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .shop-bot { display:flex; align-items:baseline; justify-content:space-between; gap:6px; }
  .shop .num { font-weight:700; color:var(--ink); font-variant-numeric:tabular-nums; }
  .shop .num.muted { color:var(--ink-3); font-weight:400; }
  /* This listing's price vs true open-market price (not MSRP) — is it actually worth buying now.
     Sized to match the price next to it, not the micro-labels: it's the most decision-relevant
     text on the row, and 10px buried it at the same weight as throwaway chrome (2026-09-07 audit). */
  .deal { font:800 12px/1 var(--body); letter-spacing:.02em; white-space:nowrap; }
  .deal.buy { color:#5fd65f; } .deal.pass { color:#ff8a80; } .deal.even { color:var(--ink-3); }
  .num-wrap { display:flex; flex-direction:column; align-items:flex-end; gap:2px; }
  .st { display:inline-flex; align-items:center; gap:4px; font:700 10px/1 var(--body); letter-spacing:.06em; text-transform:uppercase; padding:4px 6px; border-radius:5px; flex:none; }
  .st svg { width:10px; height:10px; }
  .st.in { background:rgba(12,163,12,.18); color:#5fd65f; }
  .st.out { background:rgba(137,135,129,.16); color:var(--ink-3); }
  .st.unknown { background:rgba(250,178,25,.16); color:var(--warn); }
  .shop .ago { color:var(--ink-3); font-size:11px; }
  .empty { text-align:center; color:var(--ink-3); padding:60px 0; }
  .cal-empty { flex:none; display:flex; align-items:center; color:var(--ink-3); font-size:13px; padding:0 4px; height:150px; }
  .retired { margin-top:18px; } .retired summary { cursor:pointer; padding:10px 0; list-style:none; } .retired summary::-webkit-details-marker { display:none; }
  .retired .row { opacity:.6; }
  .hot { display:inline-flex; align-items:center; gap:4px; color:var(--ink-2); font-size:11px; font-weight:700; }
  .hot svg { width:11px; height:11px; color:var(--accent); }
  footer { color:var(--ink-3); font-size:12px; padding:18px 0 10px; display:flex; flex-direction:column; gap:4px; }

  /* Product sheet: tap a row or a hot tile. Bottom sheet on phones, centered card from 640px. */
  .row { cursor:pointer; }
  dialog.sheet { border:0; padding:0; margin:0; max-width:none; max-height:none; width:100%; background:transparent; color:inherit; position:fixed; inset:auto 0 0 0; }
  dialog.sheet::backdrop { background:rgba(5,7,16,.74); backdrop-filter:blur(10px); }
  .sheet-card { position:relative; background:linear-gradient(180deg,#181d36,#0e1226 60%); border:1px solid var(--line-2); border-radius:22px 22px 0 0; padding:0 18px max(20px, env(safe-area-inset-bottom));
    max-height:88vh; overflow:auto; scrollbar-width:thin; scrollbar-color:var(--line-2) transparent; }
  .sheet-card::-webkit-scrollbar { width:6px; } .sheet-card::-webkit-scrollbar-thumb { background:var(--line-2); border-radius:3px; }
  .grip { width:40px; height:4px; border-radius:2px; background:var(--line-2); margin:10px auto 0; }
  .sheet-x { position:absolute; top:12px; right:12px; z-index:2; width:36px; height:36px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--ink-2); display:grid; place-items:center; cursor:pointer; transition:background .15s, color .15s; }
  .sheet-x svg { width:16px; height:16px; }
  .sheet-x:hover { background:var(--card-2); color:var(--ink); }
  .sheet-art { position:relative; height:190px; width:min(100%, 250px); margin:14px auto 6px; }
  .sheet-art img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; transform:rotate(-3deg);
    filter:drop-shadow(0 26px 30px rgba(0,0,0,.7)) drop-shadow(0 0 40px rgba(242,177,52,.22)); animation:pop .55s cubic-bezier(.16,1,.3,1) both .06s; }
  .sheet-art svg { position:absolute; left:50%; top:50%; width:48px; height:48px; transform:translate(-50%,-50%); color:var(--ink-3); }
  @keyframes pop { from { opacity:0; transform:translateY(26px) scale(.88) rotate(-9deg);} }
  .sheet-title { font:800 24px/1.1 var(--display); letter-spacing:-.02em; margin:6px 0 10px; text-wrap:balance; }
  .matched { color:var(--ink-3); font-size:11px; margin:-6px 0 12px; }
  /* Verdict: the sheet's one piece of content the row doesn't already say — a recommendation
     synthesized across every listing, not another restatement of MSRP/Market (David flagged those
     as shown twice with a duplicate TCGplayer link, 2026-09-07). */
  .verdict { display:flex; align-items:flex-start; gap:10px; padding:12px 14px; border-radius:14px; font:600 14px/1.4 var(--body); margin:14px 0; }
  .verdict svg { width:17px; height:17px; flex:none; margin-top:2px; }
  .verdict b { font-weight:800; }
  .verdict.buy { background:rgba(12,163,12,.14); border:1px solid rgba(12,163,12,.4); color:#bdf7bd; }
  .verdict.buy svg { color:#5fd65f; }
  .verdict.pass { background:rgba(255,90,78,.12); border:1px solid rgba(255,90,78,.35); color:#ffd3cd; }
  .verdict.pass svg { color:#ff8a80; }
  .verdict.even { background:var(--card-2); border:1px solid var(--line); color:var(--ink-2); }
  .verdict.even svg { color:var(--ink-3); }
  .matched a { color:var(--ink-2); }
  .sheet-sec { margin:16px 0 6px; }
  .stores { display:flex; flex-direction:column; gap:6px; }
  .store { display:grid; grid-template-columns:8px minmax(0,1fr) auto auto 14px; align-items:center; gap:10px; padding:9px 12px; border-radius:10px; background:var(--card); border:1px solid var(--line);
    text-decoration:none; color:var(--ink-2); font-size:13px; transition:background .15s, border-color .15s, transform .12s; }
  .store:hover { background:var(--card-2); border-color:var(--line-2); } .store:active { transform:scale(.99); }
  .store .id { width:8px; height:8px; border-radius:50%; background:var(--c); }
  .store .r { font-weight:700; color:var(--ink); min-width:0; } .store .r small { display:block; font-weight:400; color:var(--ink-3); font-size:11px; }
  .store .num { font-weight:700; color:var(--ink); }
  .go { width:14px; height:14px; color:var(--ink-3); flex:none; }
  .cmp-link { display:inline-flex; align-items:center; gap:3px; color:inherit; text-decoration:none; border-bottom:1px dotted var(--line-2); }
  .cmp-link:hover { color:var(--ink-2); border-bottom-color:var(--ink-2); }
  .cmp-link .go { width:9px; height:9px; }
  .signals { display:flex; flex-wrap:wrap; gap:6px 14px; color:var(--ink-2); font-size:12px; margin-top:14px; }
  .signals span { display:inline-flex; align-items:center; gap:5px; } .signals svg { width:12px; height:12px; color:var(--accent); }
  .signals b { color:var(--ink); }
  dialog.sheet[open] .sheet-card { animation:sheetUp .42s cubic-bezier(.16,1,.3,1) both; }
  @keyframes sheetUp { from { transform:translateY(40px); opacity:0; } }
  @media (prefers-reduced-motion:reduce) { .sheet-card, .sheet-art img { animation:none !important; } }
  @media (min-width:640px) {
    dialog.sheet { inset:0; width:min(92vw, 54rem); height:fit-content; margin:auto; }
    .sheet-card { border-radius:22px; padding:28px 28px 28px 24px; max-height:86vh; display:grid; grid-template-columns:260px minmax(0,1fr); column-gap:28px; align-items:start; }
    .grip { display:none; }
    .sheet-art { height:300px; width:260px; margin:6px 0 0; position:sticky; top:0; }
    .sheet-title { font-size:30px; padding-right:36px; }
  }

  @media (pointer:coarse) { .seg button, .chip, .sortsel, .selwrap, .shop { min-height:44px; } .search { min-height:44px; } }
  @media (min-width:640px) {
    .wrap { max-width:60rem; padding:0 24px; }
    .reel-wrap { margin:18px -24px 0; } .reel-head { padding:0 24px 8px; } .track { padding:6px 24px 16px; gap:12px; }
    .cal-wrap { margin:18px -24px 0; } .cal-wrap .reel-head { padding:0 24px 8px; } .cal { padding:4px 24px 14px; gap:12px; } .rel { width:150px; }
    .tile { width:184px; } .tile .art { height:150px; } .tile .t { font-size:14px; }
    header { padding:36px 0 12px; }
    h1 { font-size:44px; }
    .mascot { width:auto; height:120px; margin-left:-10px; }
    .hero { gap:18px; }
    .stats { grid-template-columns:repeat(4,1fr); gap:10px; }
    .bar { margin:14px -24px 14px; padding:10px 24px; display:flex; flex-wrap:wrap; gap:8px 10px; align-items:center; }
    .search { flex:1 1 220px; }
    .strip { margin:0; padding:0; overflow:visible; flex-wrap:wrap; mask-image:none; -webkit-mask-image:none; display:contents; }
    .count { margin:0 0 0 auto; }
    .row { grid-template-columns:92px minmax(0,1.3fr) minmax(260px,1fr); grid-template-areas:"thumb head meter" "thumb shops shops"; column-gap:16px; padding:12px 16px; align-items:center; }
    .thumb { grid-area:thumb; width:92px; height:92px; border-radius:12px; }
    .head { grid-area:head; } .meter { grid-area:meter; } .shops { grid-area:shops; }
    .name { font-size:18px; }
  }
  @media (min-width:1024px) {
    .wrap { max-width:72rem; }
    .row { grid-template-columns:92px minmax(0,1.2fr) 320px minmax(0,1.3fr); grid-template-areas:"thumb head meter shops"; }
  }
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="hero">
    <img class="mascot" src="mascot.webp" alt="" decoding="async">
    <div>
      <h1>Restock <em>Watch</em></h1>
      <p class="sub">Sealed Pokemon and One Piece, first-party listings only. Market price from TCGplayer.</p>
      <a class="join" id="join" href="#" target="_blank" rel="noopener" hidden><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.3 5.4A16 16 0 0 0 15.4 4l-.2.4a15 15 0 0 1 3.6 1.8 13 13 0 0 0-13.6 0A15 15 0 0 1 8.8 4.4L8.6 4a16 16 0 0 0-3.9 1.4C2.2 9.1 1.5 12.7 1.8 16.3A16 16 0 0 0 6.7 19l1-1.6a10 10 0 0 1-1.6-.8l.4-.3a11.5 11.5 0 0 0 11 0l.4.3-1.6.8 1 1.6a16 16 0 0 0 4.9-2.7c.4-4.2-.7-7.8-2.9-10.9ZM8.7 14.1c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm6.6 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>Join the drop alerts on Discord</a>
    </div>
  </div>
  <div class="stats" id="stats"></div>
</header>

<section class="reel-wrap" id="reelWrap" hidden>
  <div class="reel-head"><span class="micro">Hot right now</span></div>
  <div class="reel" id="reel"><div class="track" id="track"></div></div>
</section>

<section class="cal-wrap" id="calWrap" hidden>
  <button class="reel-head cal-toggle" id="calToggle"><span class="micro">Coming up</span><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></button>
  <div class="cal-collapse" id="calCollapse"><div class="cal" id="cal"></div></div>
</section>

<div class="bar">
  <label class="search"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="q" type="search" placeholder="Search products" autocomplete="off"></label>
  <div class="strip">
    <div class="seg" id="game"><button data-v="" class="on">All</button><button data-v="Pokemon">Pokemon</button><button data-v="One Piece">One Piece</button><button data-v="Riftbound">Riftbound</button></div>
    <span id="retailers" style="display:contents"></span>
    <button class="chip toggle" id="inStockToggle" style="--c:var(--good)"><span class="sw"></span>In stock</button>
    <div class="selwrap" id="kindWrap"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16l-6 7.5V19l-4 2v-8.5z"/></svg><select class="sortsel" id="kind"><option value="">All types</option><option value="Booster Box">Box</option><option value="ETB">ETB</option><option value="Bundle">Bundle</option><option value="Collection">Collection</option><option value="Deck">Deck</option><option value="Packs">Packs</option></select><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></div>
    <div class="selwrap"><svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 6h13M7 12h9M7 18h5"/><path d="m3 6 .01.01M3 12l.01.01M3 18l.01.01"/></svg><select class="sortsel" id="sort"><option value="hot">Hottest first</option><option value="stock">In stock first</option><option value="premium">Biggest premium</option><option value="name">Name</option><option value="msrp">MSRP</option></select><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></div>
  </div>
  <div class="count" id="count"></div>
</div>

<div class="list" id="list"></div>
<details class="retired" id="retired" hidden><summary class="micro"><span id="retiredCount"></span> retired &middot; no stock anywhere for a long time, no longer polled</summary><div class="list" id="retiredList"></div></details>
<footer><span>Snapshot <span id="gen"></span>, built on the watcher PC. <span id="poll"></span></span><span>Feeds: <span id="feeds"></span></span></footer>
</div>

<dialog class="sheet" id="sheet" aria-labelledby="sheetTitle">
  <div class="sheet-card" id="sheetCard">
    <div class="grip"></div>
    <button class="sheet-x" id="sheetX" aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
    <div class="sheet-art" id="sheetArt"></div>
    <div class="sheet-body" id="sheetBody"></div>
  </div>
</dialog>
<div class="toast" id="toast" hidden></div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const RET = {target:{l:'Target',c:'var(--target)'}, bestbuy:{l:'Best Buy',c:'var(--bestbuy)'}, walmart:{l:'Walmart',c:'var(--walmart)'}, gamestop:{l:'GameStop',c:'var(--gamestop)'}};
const ST = {
  in:{l:'In stock', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5L20 7"/></svg>'},
  out:{l:'Sold out', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M5 12h14"/></svg>'},
  unknown:{l:'Not checked', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2.5"/></svg>'}
};
const PLACEHOLDER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/></svg>';
// One glyph per game: filled pokeball, stroked anchor (David kept it over a Straw Hat skull, more
// distinctive at 11px), Riftbound's orange swirl. Hue reserved per game, used on the glyph only.
const GAME = {
  'Pokemon':   {c:'#ffcf4a', i:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 1 9.8 8.2h-6.1a3.8 3.8 0 0 0-7.4 0H2.2A10 10 0 0 1 12 2z"/><path d="M2.2 13.8h6.1a3.8 3.8 0 0 0 7.4 0h6.1A10 10 0 0 1 2.2 13.8z"/><circle cx="12" cy="12" r="2"/></svg>'},
  'One Piece': {c:'#3ddbc4', i:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2.4"/><path d="M12 7.4V21M5 13a7 7 0 0 0 14 0M8.5 13H5M19 13h-3.5"/></svg>'},
  'Riftbound': {c:'#ff8a1f', i:'<svg viewBox="0 0 24 24" fill="currentColor">' + [0, 72, 144, 216, 288].map(a => `<path d="M11 12C10 5 16 1 23 4 17 4.5 15 8 15 12 15 14 12 14.5 11 12z" transform="rotate(${a} 12 12)"/>`).join('') + '</svg>'},
};
const gameTag = name => { const g = GAME[name]; return `<span class="tag" style="--gc:${g ? g.c : 'currentColor'}">${g ? g.i : ''}${name}</span>`; };
// Icon-only glyph (no text chip) for tight spaces; title carries the game name for a11y/hover.
const gameGlyph = name => { const g = GAME[name]; if (!g) return ''; return `<span class="gi" style="--gc:${g.c}" title="${name}">${g.i}</span>`; };
const F = {q:'', game:'', kind:'', ret:new Set(Object.keys(RET)), status:'', sort:'hot'};
const FLAME = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z"/></svg>';
const $ = s => document.querySelector(s);
const money = v => v == null ? null : '$' + Number(v).toFixed(2);
const ago = ts => { if(!ts) return ''; const d = Math.max(0, Math.round(D.generated - ts)); return d<90? d+'s' : d<5400? Math.round(d/60)+'m' : d<172800? Math.round(d/3600)+'h' : Math.round(d/86400)+'d'; };

function stats(){
  const listings = D.groups.reduce((n,g)=>n+g.listings.length,0);
  const inStock = D.groups.filter(g=>g.in_stock).length;
  const prems = D.groups.map(g=>g.premium).filter(Boolean).sort((a,b)=>a-b);
  const med = prems.length ? prems[Math.floor(prems.length/2)] : null;
  $('#stats').innerHTML = [
    [D.groups.length, 'products watched', ''],
    [listings, 'retailer listings', ''],
    [inStock, 'in stock now', inStock ? '<span class="dot"></span>' : ''],
    [med ? med.toFixed(1)+'×' : '—', prems.length ? 'median market over MSRP, '+prems.length+' priced' : 'market over MSRP, no prices yet', ''],
  ].map(([v,l,x])=>`<div class="stat"><div class="v">${x}${v}</div><div class="l">${l}</div></div>`).join('');
}

// Single source of truth for the premium verdict; the meter headline is the only place it renders.
// Color still grades severity (green/amber/red); the word doesn't need to try too — "2.5x
// scalped" said the same thing twice, awkwardly (David, 2026-09-07).
const premiumVerdict = p => p == null ? null : p <= 1.15 ? {cls:'ok', t:'at MSRP'} : {cls: p <= 2 ? 'hi' : 'wild', t:'over MSRP'};
// The ratio + verdict word alone: the signal ("3.0x scalped"). Used on the row, where the actual
// MSRP/Market breakdown is a click away, not a second thing to scan past for every product.
function meterHead(g){
  const m = g.market, p = g.premium, v = premiumVerdict(p);
  return p ? `<div class="cmp-head ${v.cls}"><b>${p.toFixed(1)}×</b><span>${v.t}</span></div>`
           : `<div class="cmp-head muted"><span>${m? 'no MSRP set' : 'no market price yet'}</span></div>`;
}
// showHead: the sheet wants the exact "3.0x over MSRP" readout; the row doesn't need to say the
// same thing three ways (number, word, and bar length) — the bar alone carries it once the
// Market bar's own color grades severity (green/amber/red), not just a decorative gradient
// (David, 2026-09-07).
function meter(g, showHead){
  const m = g.market, v = premiumVerdict(g.premium);
  const max = Math.max(g.msrp||0, m? m.price:0) || 1;
  // The link icon sits on the label, not the number — appended after the number broke the
  // right-aligned edge between the MSRP and MARKET value columns (David, 2026-09-07).
  const bar = (cls, label, val, href) => `<div class="cmp-row"><span class="cmp-l">${href ? `<a class="cmp-link" href="${href}" target="_blank" rel="noopener" title="View on TCGplayer">${label}${ICO.go}</a>` : label}</span><span class="cmp-t"><span class="cmp-b ${cls}" style="width:${val? Math.max(3, val/max*100):0}%"></span></span><span class="cmp-v num">${val? money(val) : '—'}</span></div>`;
  return `<div class="meter">${showHead? meterHead(g) : ''}${bar('msrp','MSRP',g.msrp)}${bar(`mkt ${v?v.cls:''}`,'Market',m? m.price:null, m? m.url:null)}</div>`;
}

// This retailer's asking price vs the true open-market price (not MSRP): is buying it right
// now actually a deal, or is TCGplayer itself cheaper? Only meaningful while it's orderable.
function dealBadge(l, m){
  if (l.status !== 'in' || !l.price || !m || !m.price) return '';
  const diff = l.price - m.price;
  if (Math.abs(diff) / m.price < 0.03) return `<span class="deal even">≈ MARKET</span>`;
  return diff < 0 ? `<span class="deal buy">BUY · ${money(-diff)} under</span>` : `<span class="deal pass">PASS · ${money(diff)} over</span>`;
}

function shop(l, m){
  const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'};
  const s = ST[l.status];
  return `<a class="shop" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}" title="${l.checked ? 'checked ' + ago(l.checked) + ' ago' : 'not checked yet'}">
    <div class="shop-top"><span class="id"></span><span class="r">${r.l}</span><span class="st ${l.status}">${s.i}${s.l}</span></div>
    <div class="shop-bot">${l.price? `<span class="num">${money(l.price)}</span>`:'<span class="num muted">—</span>'}${dealBadge(l, m)}</div>
  </a>`;
}
// A single retailer stretched into the same two-line card as a multi-retailer row left a card
// that's visibly short of full width — a box that should be bigger but isn't. One listing gets a
// compact single-line pill instead, sized to its content, so a natural gap after it reads as a
// small tag, not a box that looks broken (David: "u love gaps dont u", 2026-09-07).
function shopSolo(l, m){
  const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'};
  const s = ST[l.status];
  return `<a class="shop solo" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}" title="${l.checked ? 'checked ' + ago(l.checked) + ' ago' : 'not checked yet'}">
    <span class="id"></span><span class="r">${r.l}</span>${l.price? `<span class="num">${money(l.price)}</span>`:''}${dealBadge(l, m)}<span class="st ${l.status}">${s.i}${s.l}</span>
  </a>`;
}

// Rows the same height needs the two things that actually varied — name length and listing
// count — normalized, not just the bars (David wants those back) hidden or shown. Name clamps to
// 2 lines with that height always reserved; more than 2 listings collapses to a "+N more" tag
// that opens the sheet, since 84 of 86 products have 1-2 listings anyway (2026-09-07).
const SHOP_CAP = 2;
function row(g){
  const over = g.listings.length - SHOP_CAP;
  const visible = over > 0 ? g.listings.slice(0, SHOP_CAP) : g.listings;
  let shops = g.listings.length === 1 ? shopSolo(g.listings[0], g.market) : visible.map(l => shop(l, g.market)).join('');
  if (over > 0) shops += `<button class="shop more" data-key="${g.key}">+${over} more</button>`;
  return `<div class="row ${g.in_stock?'in':''}" data-key="${g.key}">
    <div class="thumb">${g.img? `<img src="${g.img}" alt="" loading="lazy" decoding="async">` : PLACEHOLDER}</div>
    <div class="head"><div class="name">${gameGlyph(g.game)}${g.name}</div><div class="meta">${g.buzz? `<span class="hot" title="mentions in the deal subreddits this week">${FLAME}${g.buzz} this week</span>`:''}${g.retired? `<span class="micro">${g.retired}</span>`:''}</div></div>
    ${meter(g, false)}
    <div class="shops">${shops}</div>
  </div>`;
}

function apply(){
  const q = F.q.trim().toLowerCase();
  const retired = D.groups.filter(g => g.retired);
  $('#retired').hidden = !retired.length;
  $('#retiredCount').textContent = retired.length;
  $('#retiredList').innerHTML = retired.map(row).join('');
  let rows = D.groups.filter(g => !g.retired).filter(g =>
    (!F.game || g.game===F.game) &&
    (!F.kind || g.kind===F.kind) &&
    (!q || g.name.toLowerCase().includes(q) || (g.market && g.market.name.toLowerCase().includes(q))) &&
    g.listings.some(l => F.ret.has(l.retailer) && (!F.status || l.status===F.status))
  ).map(g => ({...g, listings: g.listings.filter(l => F.ret.has(l.retailer) && (!F.status || l.status===F.status))}));
  const s = F.sort;
  rows.sort((a,b)=> s==='hot' ? (b.hot - a.hot) || a.name.localeCompare(b.name)
              : s==='premium' ? (b.premium||0)-(a.premium||0) : s==='name' ? a.name.localeCompare(b.name) : s==='msrp' ? (b.msrp||0)-(a.msrp||0)
              : (b.in_stock - a.in_stock) || a.game.localeCompare(b.game) || a.name.localeCompare(b.name));
  $('#list').innerHTML = rows.length ? rows.map(row).join('') : '<div class="empty">Nothing matches.</div>';
  $('#count').textContent = rows.length + ' of ' + (D.groups.length - retired.length) + ' products · updated ' + D.generated_label;
}

$('#retailers').innerHTML = Object.entries(RET).map(([k,r])=>`<button class="chip on" data-r="${k}" style="--c:${r.c}"><span class="sw"></span>${r.l}</button>`).join('');
document.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{ const k=b.dataset.r; F.ret.has(k)? F.ret.delete(k): F.ret.add(k); b.classList.toggle('on'); apply(); });
document.querySelectorAll('#game button').forEach(b=>b.onclick=()=>{ F.game=b.dataset.v; b.parentElement.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b)); apply(); drawCal(); });
$('#inStockToggle').onclick = () => { F.status = F.status ? '' : 'in'; $('#inStockToggle').classList.toggle('on', !!F.status); apply(); };
$('#kind').onchange = e => { F.kind = e.target.value; $('#kindWrap').classList.toggle('active', !!F.kind); apply(); };
$('#q').oninput = e => { F.q = e.target.value; apply(); };
$('#sort').onchange = e => { F.sort = e.target.value; apply(); };
// Hot reel: top products by hot score, doubled into one looping track.
(function reel(){
  const hot = D.groups.filter(g => !g.retired && (g.img || g.premium)).sort((a,b)=>b.hot-a.hot).slice(0,10);
  if (hot.length < 3) return;
  const wrap = $('#reelWrap'), reelEl = $('#reel'), track = $('#track');
  wrap.hidden = false;
  const tile = g => `<a class="tile${g.in_stock ? ' in' : ''}" href="#${encodeURIComponent(g.key)}" data-key="${g.key}"><div class="art">${g.img? `<img src="${g.img}" alt="" loading="lazy" decoding="async">` : PLACEHOLDER}</div><div class="t">${g.name}</div><div class="x">${g.in_stock? '<span class="in">In stock</span>' : ''}${g.premium? `<b>${g.premium.toFixed(1)}×</b>`:''}</div></a>`;
  track.innerHTML = hot.map(tile).join('') + hot.map(tile).join('');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let pos = 0, vel = 0, drag = null, moved = 0, hover = false, idleAt = 0, setW = 0, tapTile = null;
  const measure = () => { setW = track.scrollWidth / 2; };
  measure(); addEventListener('resize', measure);
  function frame(){
    const now = performance.now();
    if (drag) { /* position follows pointer */ }
    else if (Math.abs(vel) > 0.05) { pos += vel; vel *= 0.955; }
    else if (!reduced && now - idleAt > 700) { pos += hover ? 0.16 : 0.4; }
    if (setW > 0) { pos = ((pos % setW) + setW) % setW; }
    track.style.transform = `translateX(${-pos}px)`;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  reelEl.addEventListener('mouseenter', ()=>hover=true); reelEl.addEventListener('mouseleave', ()=>hover=false);
  // setPointerCapture retargets the follow-up click to the reel itself, so a click listener on the
  // track never fires. Decide tap-vs-drag on pointerup instead and open the sheet from there.
  reelEl.addEventListener('pointerdown', e => { tapTile = e.target.closest('.tile'); drag = {x:e.clientX, pos, last:e.clientX, t:performance.now()}; moved = 0; vel = 0; reelEl.classList.add('drag'); reelEl.setPointerCapture(e.pointerId); });
  reelEl.addEventListener('pointermove', e => { if(!drag) return; const dx = e.clientX - drag.x; moved = Math.max(moved, Math.abs(dx)); pos = drag.pos - dx; const now = performance.now(); vel = -(e.clientX - drag.last) * 2; vel = Math.max(-150, Math.min(150, vel)); drag.last = e.clientX; drag.t = now; });
  const end = e => { if(!drag) return; drag = null; idleAt = performance.now(); reelEl.classList.remove('drag');
    if (e.type === 'pointerup' && moved <= 6 && tapTile) { vel = 0; openKey(tapTile.dataset.key); } tapTile = null; };
  reelEl.addEventListener('pointerup', end); reelEl.addEventListener('pointercancel', end);
  reelEl.addEventListener('click', e => { if (e.target.closest('.tile')) e.preventDefault(); });
})();
// Product sheet: one product's full picture. Opened by row tap, hot tile tap, or a #key deep link.
const SHEET = $('#sheet');
const ICO = {
  go:'<svg class="go" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M9 7h8v8"/></svg>',
};
const live = () => D.groups.filter(x => !x.retired);
const VERDICT_ICON = {
  buy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5L20 7"/></svg>',
  pass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  even: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M5 12h14"/></svg>',
};
// The one thing the sheet says that the row doesn't: a plain-language recommendation synthesized
// across every listing, instead of the same MSRP/Market numbers shown a second time.
function bestDeal(g){
  const m = g.market;
  const inStock = g.listings.filter(l => l.status === 'in' && l.price);
  // Nothing in stock is already unambiguous from every "SOLD OUT" pill in the retailer list right
  // below — a whole callout box just to restate that read as dead weight (David, 2026-09-07).
  if (!inStock.length || !m || !m.price) return null;
  const best = inStock.reduce((a, b) => a.price < b.price ? a : b);
  const r = RET[best.retailer] || {l: best.retailer};
  const diff = best.price - m.price;
  if (diff <= -m.price * 0.03) return { cls:'buy', text: `Best move: <b>${r.l}</b> at <b>${money(best.price)}</b>, ${money(-diff)} under today's market.` };
  if (diff >= m.price * 0.03) return { cls:'pass', text: `Every listing runs over market right now. Closest is <b>${r.l}</b> at ${money(best.price)}.` };
  return { cls:'even', text: `<b>${r.l}</b> at ${money(best.price)} is right at market price.` };
}
function openSheet(g){
  const p = g.premium, m = g.market, rank = live().findIndex(x => x.key === g.key) + 1;
  $('#sheetArt').innerHTML = g.img ? `<img src="${g.img}" alt="">` : PLACEHOLDER;
  const deal = bestDeal(g);
  const stores = g.listings.map(l => { const r = RET[l.retailer] || {l:l.retailer, c:'var(--ink-3)'}, s = ST[l.status];
    return `<a class="store" href="${l.url}" target="_blank" rel="noopener" style="--c:${r.c}"><span class="id"></span><span class="r">${r.l}<small>${l.checked ? 'checked ' + ago(l.checked) + ' ago' : 'not checked yet'}</small></span><span class="num-wrap"><span class="num">${l.price ? money(l.price) : '—'}</span>${dealBadge(l, m)}</span><span class="st ${l.status}">${s.i}${s.l}</span>${ICO.go}</a>`; }).join('');
  const sig = [
    rank ? `<span>${FLAME}<b>#${rank}</b> hottest of ${live().length}</span>` : '',
    g.buzz ? `<span>${FLAME}<b>${g.buzz}</b> deal-sub mentions this week</span>` : '',
    g.last_in_stock ? `<span>${ST.unknown.i}last in stock <b>${ago(g.last_in_stock)}</b> ago</span>` : `<span>${ST.unknown.i}never seen in stock</span>`,
  ].join('');
  $('#sheetBody').innerHTML = `<div class="meta">${gameTag(g.game)}${g.in_stock ? `<span class="tag" style="--gc:#5fd65f">${ST.in.i}In stock now</span>` : ''}${g.retired ? `<span class="micro">${g.retired}</span>` : ''}</div>
    <h2 class="sheet-title" id="sheetTitle">${g.name}</h2>
    ${m && m.name && m.name !== g.name ? `<div class="matched">TCGplayer match: <a href="${m.url}" target="_blank" rel="noopener">${m.name}</a></div>` : ''}
    ${meter(g, true)}
    ${deal ? `<div class="verdict ${deal.cls}">${VERDICT_ICON[deal.cls]}<span>${deal.text}</span></div>` : ''}
    <div class="micro sheet-sec">Where it sells</div>
    <div class="stores">${stores}</div>
    <div class="signals">${sig}</div>`;
  if (!SHEET.open) SHEET.showModal();
  $('#sheetCard').scrollTop = 0;
  history.replaceState(null, '', '#' + encodeURIComponent(g.key));
}
function openKey(k){ const g = D.groups.find(x => x.key === k); if (g) openSheet(g); }
const closeSheet = () => { if (SHEET.open) SHEET.close(); };
SHEET.addEventListener('close', () => { if (location.hash) history.replaceState(null, '', location.pathname + location.search); });
SHEET.addEventListener('click', e => { if (e.target === SHEET) closeSheet(); });
$('#sheetX').onclick = closeSheet;
// Selecting/copying the product name kept getting swallowed as a row-open click. The name now
// copies to the clipboard instead of opening the sheet; the rest of the row still opens it
// (David, 2026-09-07).
let toastTimer;
function showToast(msg){
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('show'); setTimeout(() => { t.hidden = true; }, 250); }, 1400);
}
['#list', '#retiredList'].forEach(s => $(s).addEventListener('click', e => {
  if (e.target.closest('a')) return;
  const nameEl = e.target.closest('.name');
  if (nameEl) {
    const text = nameEl.textContent.trim();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => showToast('Copied product name')).catch(() => showToast('Could not copy — select the text instead'));
    } else showToast('Could not copy — select the text instead');
    return;
  }
  const r = e.target.closest('.row'); if (r) openKey(r.dataset.key);
}));
const fromHash = () => { if (location.hash.length > 1) openKey(decodeURIComponent(location.hash.slice(1))); };
addEventListener('hashchange', fromHash);
$('#gen').textContent = D.generated_label;
if (D.discord_invite) { const j = $('#join'); j.href = D.discord_invite; j.hidden = false; }
$('#poll').textContent = D.last_poll ? 'Last poll ' + ago(D.last_poll) + ' before the snapshot.' : 'No polls recorded yet.';
$('#feeds').textContent = D.feeds.join(', ');
// Coming up: release calendar from config `releases:`. The game filter (Pokemon/One Piece/
// Riftbound) applies here too — "only show me Riftbound" should mean the calendar as well as the
// list. Retailer/type/in-stock filters don't: those describe live listings, and an unreleased
// product doesn't have a retailer or type yet, so they'd have nothing to filter against.
const ALL_RELEASES = D.releases || [];
function calCollapsed(){ try { return localStorage.getItem('tcgwatch:calCollapsed') === '1'; } catch(e) { return false; } }
function setCalCollapsed(v){
  $('#calWrap').classList.toggle('collapsed', v);
  try { localStorage.setItem('tcgwatch:calCollapsed', v ? '1' : '0'); } catch(e) {}
}
function drawCal(){
  if (!ALL_RELEASES.length) return;
  $('#calWrap').hidden = false;
  $('#calWrap').classList.toggle('collapsed', calCollapsed());
  const R = ALL_RELEASES.filter(r => !F.game || r.game === F.game);
  const item = r => { const d = r.days, cls = d < 0 ? 'now' : d <= 7 ? 'soon' : d <= 30 ? 'near' : '';
    const when = d < 0 ? 'out now' : d === 0 ? 'today' : d === 1 ? 'tomorrow' : d <= 60 ? `in ${d} days` : `in ${Math.round(d / 7)} weeks`;
    const tag = r.source ? 'a' : 'div', href = r.source ? ` href="${r.source}" target="_blank" rel="noopener"` : '';
    const g = GAME[r.game] || {c:'currentColor', i:''};
    return `<${tag} class="rel ${cls}" style="--gc:${g.c}"${href} title="${r.game} — ${(r.note || '').replace(/"/g, '&quot;')}"><div class="rel-top"><div><div class="date-mon">${r.mon}</div><div class="date-day">${r.day}</div></div><div class="rel-icon">${g.i}</div></div><div class="rel-n">${r.name}</div><div class="rel-when">${when}</div></${tag}>`; };
  const cal = $('#cal');
  cal.scrollLeft = 0;
  cal.innerHTML = R.length ? R.map(item).join('') : `<div class="cal-empty">Nothing upcoming for ${F.game || 'this filter'} yet.</div>`;
}
$('#calToggle').onclick = () => setCalCollapsed(!$('#calWrap').classList.contains('collapsed'));
(function calSetup(){
  const cal = $('#cal');
  // Mouse users: vertical wheel scrolls the strip sideways. Each tick nudges a target rather than
  // jumping scrollLeft directly, then a per-frame lerp glides toward it — fast at first, easing
  // out as it approaches (David: wheel scroll "too fast", wanted accel/decel, 2026-09-07).
  // CSS scroll-snap fights small per-frame scrollLeft writes (each one can get pulled back
  // toward the nearest snap point), which stalled the ease well short of its target — the same
  // reason the drag path below already turns snap off for its duration; the wheel-ease needs the
  // same treatment (David: wheel scroll "too fast", wanted accel/decel, 2026-09-07).
  let wheelTarget = null;
  (function easeWheel(){
    if (wheelTarget !== null) {
      const d = wheelTarget - cal.scrollLeft;
      if (Math.abs(d) < 0.5) { cal.scrollLeft = wheelTarget; wheelTarget = null; cal.classList.remove('drag'); }
      else cal.scrollLeft += d * 0.18;
    }
    requestAnimationFrame(easeWheel);
  })();
  cal.addEventListener('wheel', e => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX) || cal.scrollWidth <= cal.clientWidth) return;
    e.preventDefault();
    const max = cal.scrollWidth - cal.clientWidth;
    cal.classList.add('drag');
    wheelTarget = Math.max(0, Math.min(max, (wheelTarget ?? cal.scrollLeft) + e.deltaY));
  }, {passive:false});
  let drag = null, moved = 0, tapCard = null;
  // setPointerCapture (needed so a mouse can click-drag this like the reel; touch already scrolls
  // natively) retargets the click to #cal, so the card's own <a> never navigates. Open the tapped
  // card from the click handler itself: window.open from pointerup counted as a weaker user
  // activation and popup blockers ate it, which read as "clicking does nothing" (2026-09-07).
  cal.addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse') return; tapCard = e.target.closest('.rel'); wheelTarget = null;
    drag = {x:e.clientX, left:cal.scrollLeft}; moved = 0; cal.setPointerCapture(e.pointerId); cal.classList.add('drag'); });
  cal.addEventListener('pointermove', e => { if (!drag) return; const dx = e.clientX - drag.x; moved = Math.max(moved, Math.abs(dx)); cal.scrollLeft = drag.left - dx; });
  const end = () => { if (!drag) return; drag = null; cal.classList.remove('drag'); };
  cal.addEventListener('pointerup', end); cal.addEventListener('pointercancel', end);
  cal.addEventListener('click', e => {
    const card = tapCard, dragged = moved > 6; tapCard = null; moved = 0;
    if (dragged) { e.preventDefault(); e.stopPropagation(); return; }
    if (card && card.tagName === 'A' && !card.contains(e.target)) { e.preventDefault(); window.open(card.href, '_blank', 'noopener'); }
  }, true);
})();
drawCal();
// Game filter buttons get the same glyphs as the tags.
document.querySelectorAll('#game button[data-v]').forEach(b => { const g = GAME[b.dataset.v]; if (g) { b.style.setProperty('--gc', g.c); b.insertAdjacentHTML('afterbegin', g.i); } });
stats(); apply(); fromHash();
</script>
</body>
</html>
"""


def build(cfg: Config, out_dir: Path) -> Path:
    data = collect(cfg, out_dir / "img")
    root = Path(__file__).resolve().parent.parent
    data["mascot"] = images.export_mascot(root / "assets" / "mascot.png", out_dir)
    page = TEMPLATE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    (out_dir / "vercel.json").write_text(json.dumps({"cleanUrls": True}), encoding="utf-8")
    return out
