# EV calculator spec (2026-09-07, built 2026-09-08 — see note below)

> **Built as tier-based, not per-card.** The original spec below assumed
> per-named-chase-card pull rates. Building against real data (tcgtalk.com,
> 168 Riftbound Unleashed packs opened) showed pull rates are published per
> RARITY TIER — Riot has never released official odds, and no source tracks
> odds per individual card. The shipped design in `tcgwatch/ev.py` sums
> `(per_box count) x (tier price)` across tiers instead of across named
> cards. Simpler, and matches what data actually exists. Kept the rest of
> this doc as the historical record of the original plan.

Scope: chase-card EV only. Base/common card value is ignored in v1 — this
answers "is the chase-card upside worth the box price", not full box EV.

First set built: **Riftbound Unleashed Booster Display** — already tracked
in config.yaml with real product IDs and MSRP, no new retailer work needed.

## Formula (as shipped)
```
box EV = sum over tiers of (per_box count) x (tier price)
verdict = box EV - box price      (positive = statistically worth opening)
```

## Data sourcing (as shipped, Riftbound Unleashed)
| Tier | Price source |
|---|---|
| Rare, Epic, Showcase/Alt Art | Live TCGplayer mean market price, via `tcgwatch/singles.py` querying TCGplayer's own `rarityName` search facet (verified real and populated 2026-09-08) |
| Overnumbered, Signed Overnumbered | Community guide's value estimate (tcgtalk.com) — too rare to reliably appear in live TCGplayer listings |
| Baron Nashor (Ultimate Rare) | Unknown — no price at all, shown as such, excluded from the EV sum |

Per-box expected counts for every tier are community data (tcgtalk.com, 168
packs opened), not an official publisher figure — Riot has not released
Riftbound pack odds. See `data/pull_rates.yaml` for exact numbers and dates.

Official pull-rate odds exist reliably for Pokemon (unlike Riftbound). If
Pokemon booster boxes get pull-rate data later, check for official odds
before falling back to a wiki/community number.

## Files (as shipped)
| File | What it does |
|---|---|
| `data/pull_rates.yaml` | Sets → packs/box → tiers (name, per-box count, `rarity_query` for a live TCGplayer lookup or `price_estimate` for a community-sourced one, `match` substring to attach EV to a site.py product group) |
| `tcgwatch/singles.py` | TCGplayer singles search filtered by `rarityName`, mean/median/n per tier, cached a day in-process |
| `tcgwatch/ev.py` | `calc_ev(set_key, box_price)` — pure function; `get_or_refresh(state, set_key, box_price)` — same, cached a day in `state.json` under `ev:<set_key>` so a manual `--site` rebuild doesn't re-hit TCGplayer every time |
| `tcgwatch/site.py` | EV block on a matching product's detail sheet only, with an explicit "long-run average, not a per-box guarantee" note |

## Open items for later
- Which other sets get pull-rate tables (Pokemon booster boxes need roadmap
  item 4's TCGplayer-only watch extended, or GameNerdz unblocked, before
  they'd have a box price to compare EV against).
- Whether to eventually add base-pack value for a true full-EV number
  (v1 deliberately ignores it — commons/uncommons priced at $0.08-0.25
  mean, checked 2026-09-08, negligible next to a $120+ box).
