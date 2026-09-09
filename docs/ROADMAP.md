# Roadmap (updated 2026-09-08)

Items 1, 3, 4, 5, 6, 7 are done and live. Item 2 (daily history) is merged and
live going forward — every future day adds one real row per product,
independent of tcgcsv.com's bot protection (see Decisions). The one-time
retroactive backfill from tcgcsv.com is NOT reliable: three attempts, three
WAF blocks, real fixes each time, gave up on it deliberately (David's call).
136 real rows from the one partial run that got through are kept.

2026-09-08 also had a real concurrent-session collision: another session
(David's) was actively building a Chrome-extension bridge for the blocked
retailers (Pokemon Center, Costco, Sam's Club, Amazon) plus a Vercel
deploy-budget feature, in this same working tree, at the same time as this
coordinator. `git checkout` was refused once because it would have
overwritten their uncommitted `watcher.py` changes -- correctly left
untouched rather than forced. Resolved once David confirmed the other
session had stopped. Lesson for later: two interactive sessions (not just
subagent lanes) can collide in one working tree; there's no tooling fix for
this beyond noticing `git status` doesn't match what you expect and asking.

Working mode: parallel via worktree subagents, one coordinator session.
See "Lanes" below before dispatching. Host rule is non-negotiable.

## Next session
All queued items (1-7) are done. The only open thread is the optional
market.py/singles.py migration below -- reconsider it, or pick a new item,
next time this project is picked up.

Migrating market.py/singles.py to prefer tcgcsv.com over scraping TCGplayer
directly was the other half of
the original plan (see Decisions) but was NOT built, given how unreliable
tcgcsv.com's bot protection turned out to be for this IP. Reconsider whether
that migration is still worth it before starting it.

## Queue (all items, ordered by size/dependency)
| # | Item | Size | Status | Lane | Depends on |
|---|------|------|--------|------|------------|
| 1 | Shipping in verdict | 1 h | done | A pricing | |
| 2 | Daily market price history (append; backfill via tcgcsv.com abandoned) | 2-3 h | done (append); backfill unreliable, 136 rows kept from one partial run | A pricing | |
| 3 | 30/90-day change + sparkline | 1 h | done | A pricing | |
| 4 | Booster box price watch (TCGplayer only; GameNerdz deferred) | half day | done | B sources | |
| 5 | Riot Merch retailer module | 1-2 h | done | B sources | |
| 6 | Local shop links tab | 1 h | done | C links | |
| 7 | Build own EV calculator, Riftbound Unleashed first | half day+ | done | C links | none, self-contained |

## Lanes (parallel)
| Lane | Branch | Owns files | Status | Merge order |
|------|--------|------------|--------|-------------|
| A pricing | lane/pricing | tcgwatch/msrp.py, tcgwatch/market.py, tcgwatch/lifecycle.py, config.yaml (shipping block) | merged 2026-09-07 (item 1 only) | 3 |
| B sources | lane/sources | tcgwatch/retailers/*, tcgwatch/browser.py, config.yaml (products block) | merged 2026-09-07 | 2 |
| C links   | lane/links   | site/index.html (new tabs), tcgwatch/site.py | merged 2026-09-07 | 1 |
| ev (item 7) | lane/ev | data/pull_rates.yaml, tcgwatch/ev.py, tcgwatch/singles.py, tcgwatch/site.py | merged 2026-09-08 | 4, after C |
| history (item 2) | lane/history | tcgwatch/tcgcsv.py, tcgwatch/history.py, watch.py, watcher.py, README.md | merged 2026-09-08 | 5, last |

lane/ev was built solo (no subagent dispatch) since the coordinator had
already gathered the real pull-rate/pricing research directly -- delegating
it would have meant re-deriving the same data in a fresh context.

Lane C touches no live host and no file the other lanes touch. Merge it first,
any session, no probe needed.

Note: `isolation: "worktree"` failed for this lane because the coordinator's
cwd (~/Github) isn't itself a git repo — only tcg-restock-watch inside it is.
Worked around by branching directly in the repo instead. Fine solo; once two
lanes run at the same time, either dispatch from inside the repo path or
configure WorktreeCreate hooks first to avoid two agents editing the same
working tree at once.

## Host rule
Probes (TCGplayer chart/history endpoint, Riot Merch product XHR) run only in
the coordinator session, one request at a time, poller stopped first. Paste
the probe result into the lane's dispatch prompt. Subagents never call a live
host directly — this keeps lanes A and B, which would otherwise both hit
TCGplayer, from racing each other.

tcgcsv.com specifically: WAF-blocked this session's IP THREE times on
2026-09-08 (an AWS WAF Bot Control captcha challenge, `x-amzn-waf-action:
captcha`), with a real fix applied after each one -- a request-storm bug, a
missing browser fingerprint (fixed with curl_cffi + full headers + a
persistent session, matching this repo's existing gamestop.py precedent for
a different WAF), and an unpaced fallback scan. A single test request always
passed cleanly after each fix; the actual multi-request backfill run failed
anyway, every time, including once immediately after a fresh clean check.
Conclusion: this is very likely a genuine JavaScript challenge underneath
the captcha action, which no amount of Python-side TLS/header tuning can
pass (curl_cffi never executes JS). Backfilling from tcgcsv.com is
abandoned, deliberately, not left as a "try again" item -- see Decisions.
The daily-append side of item 2 doesn't touch tcgcsv.com at all, so this
doesn't block anything going forward.

## Merge log
- 2026-09-08: lane/history -> market-thread, no-ff merge, no conflicts.
  Merged with the tcgcsv.com backfill known-unreliable (see Host rule) --
  daily append works independently of it, so merging didn't wait on a clean
  backfill run that was abandoned anyway. Site rebuild verified clean before
  and after (one pre-existing, unrelated warning: a Best Buy product image
  URL failed to parse -- not caused by this merge).
- 2026-09-08: lane/ev -> market-thread, no-ff merge, no conflicts. Site
  rebuild verified clean; a headless Playwright pass confirmed the EV block
  renders for a matching product and is silently absent (no JS errors) for
  one without pull-rate data.
- 2026-09-08: lane/pricing -> market-thread, no-ff merge, no conflicts.
  Independently re-ran the reported sanity check before merging (matched
  exactly) and rebuilt the site clean after. All 6 shipping numbers in
  config.yaml are marked unverified/TODO in comments, not presented as
  fact — confirm against live retailers before trusting them for a real
  buy decision.
- 2026-09-07: lane/links -> market-thread, no-ff merge, no conflicts.
  Site rebuild (`python watch.py --site`) verified clean before and after.
- 2026-09-07: found 336 uncommitted lines already on market-thread (Target ->
  background-browser routing after a captcha block, Reddit RSS -> API switch)
  in files lane B needed to own. Committed as its own real change before
  dispatching lane B, so lane B branched off a clean base.
- 2026-09-07: coordinator probe against merch.riotgames.com (poller stopped
  first, 1 request) found it's plain-HTTP-pollable Next.js, not Shopify, no
  browser needed. Findings handed to lane B directly so it never touched a
  new host itself beyond 4 one-at-a-time verification requests.
- 2026-09-07: lane/sources -> market-thread, no-ff merge, no conflicts.
  Coordinator found a real gap before merging: watcher.py's run_forever()
  does a bare `cfg.intervals[retailer]` lookup with no default, which would
  KeyError on the first cycle to riotmerch/tcgplayer (lane B's own --once
  testing didn't hit this path). Added interval defaults, verified with a
  real --once run against both new retailers, then merged. README updated
  separately with the retailer-table row lane B drafted but was out of its
  file scope to add.

## Decisions
- 2026-09-07: History append starts now; backfill deferred until a probe
  confirms a source (TCGplayer chart endpoint or PriceCharting).
- 2026-09-07: Ran that probe (poller stopped, one-at-a-time, restarted after).
  Both candidates failed: TCGplayer's product page is a client-rendered SPA
  shell, no history data in the plain-HTTP response — the real call happens
  via JS after load, invisible to `requests.get`. PriceCharting has no
  Pokemon/TCG category at all (checked homepage nav + two direct searches,
  zero hits) — it's video-game/console pricing only. Item 2/3 stay blocked
  until someone runs a real browser session (agent-browser skill, network
  tab open) against a TCGplayer product page to find the actual endpoint its
  own JS calls — a bigger task than "one plain-HTTP probe," scope it as such
  next time it's picked up.
- 2026-09-07: Parallel work runs as worktree subagents from one coordinator
  session, not separate terminals. See CLAUDE.md global instructions on
  subagent tiering and worktrees.
- 2026-09-07: EV per-set link-out dropped. No existing EV calculator site
  found; David doesn't know one either. Rescoped item 7 to building our own
  (pull rates + chase-card prices via existing TCGplayer lookup), per the
  original spec table's alternate estimate (half day for a v1).
- 2026-09-08: Building item 7, found real pull-rate data (tcgtalk.com, 168
  packs opened) is published per RARITY TIER, not per named chase card --
  Riot has never released official odds. Changed the spec's design from
  per-card to per-tier accordingly: simpler, and matches what data actually
  exists. Also found TCGplayer's search API has a real, populated
  `rarityName` facet (checked live 2026-09-08), so most tiers get a live
  mean market price instead of a static estimate; only the two rarest tiers
  (too few live listings to ever show up) fall back to the community
  guide's value estimate, clearly marked as such on the site.
- 2026-09-08: Superseded the browser-network-capture plan for items 2/3.
  Found tcgcsv.com: a free, TCGplayer-sanctioned daily mirror of category/
  group/product/price data (JSON, no auth), with dated archives back to
  2024-02-08 -- real historical backfill, no browser automation needed.
  Verified live: categories/groups/products/live-prices all real, one
  archive file downloaded and correctly parsed (a card's price on a past
  date matched the trend of nearby days). Decided (with David) to also
  migrate market.py/singles.py to prefer tcgcsv over scraping TCGplayer's
  search API directly -- same data, no soft-block risk -- keeping the old
  scrape as a fallback rather than deleting it.
- 2026-09-08: Abandoned the tcgcsv.com backfill after three WAF blocks (see
  Host rule for the detail) -- David's call, given repeated failures despite
  real fixes each time. The market.py/singles.py migration to prefer tcgcsv
  was also NOT built as a result: it depends on the same host behaving
  reliably for routine, ongoing traffic (every market tick), not just a
  one-time backfill, and three blocks in one day is not a foundation to
  build routine production traffic on. Merged only the daily-append half of
  item 2, which never touches tcgcsv.com. `tcgwatch/tcgcsv.py` and the
  `--backfill-history` CLI stay in the codebase, unused by anything else, in
  case tcgcsv.com's bot protection is ever worth revisiting (e.g. via a real
  headless browser instead of curl_cffi, which can pass a JS challenge).

## Done
- 2026-09-08: 30/90-day price change + sparkline (item 3). Product sheet in
  site.py now shows an inline SVG sparkline plus 30d/90d % change, fed by
  tcgwatch/history.py's `series_for()`/`change_pct()`/`sparkline_points()`
  against the item-2 daily-append data. Hidden entirely (no box, no gap) for
  a product with fewer than two recorded days, rather than showing a flat or
  misleading line. Verified: site rebuild clean, 68 of the tracked products
  carry a populated `history` block in the built page's data; 30d/90d
  percentages will start showing once daily rows accumulate that far back --
  the sparkline itself is live now.  Committed to market-thread and pushed;
  deployed to production (https://tcg-restock-watch.vercel.app).
- 2026-09-08: Daily market price history (item 2, append half). New
  tcgwatch/history.py: `<data_dir>/price_history.jsonl`, one row per product
  per day, appended from the existing market-price tick (watcher.py) --
  zero dependency on tcgcsv.com for this part, so it's unaffected by the WAF
  issues below. `series_for()`/`change_pct()`/`sparkline_points()` are ready
  for item 3's UI. 136 real rows across 68 products already on disk from one
  partial tcgcsv.com backfill run before it was abandoned (see Decisions);
  grows by one row per product every day going forward regardless.
- 2026-09-08: EV calculator (item 7), Riftbound Unleashed. New tcgwatch/ev.py
  + tcgwatch/singles.py + data/pull_rates.yaml. Tier-based, not per-card (see
  Decisions). Rare/Epic/Showcase tiers use a live TCGplayer mean price
  (cached a day in state.json); Overnumbered/Signed Overnumbered use the
  community guide's value estimate, marked as such on the site. Baron Nashor
  (Ultimate Rare) has no price at all -- shown as "unknown", excluded from
  the EV sum rather than silently treated as zero. Site shows the EV block
  only on a matching product's detail sheet, with an explicit "long-run
  average, not a per-box guarantee" note (a few rare big hits skew the mean
  up). As of 2026-09-08: EV $444.17 vs current market price $194.05
  (+$250.12) for Riftbound Unleashed Booster Display.
- 2026-09-08: Shipping in the verdict (item 1). New `shipping:` block in
  config.yaml (free-shipping threshold + flat fee per retailer, all 6
  numbers flagged unverified/TODO — no web access to confirm them). New
  `msrp.landed_price()`; `msrp.verdict()` takes an optional `retailer` arg
  and bases accept/reject on landed price while still showing the raw item
  price, calling out shipping only when it changes the verdict. Old
  behavior preserved when `retailer` is omitted.
- 2026-09-07: Local shop links tab (item 6). 3 shops confirmed via web
  search (Wizards store locator, Yelp, shop sites): Legends Comics and
  Games (Milpitas), RNG Therapy Card Lounge (San Jose), Game Corner San
  Jose. Static list, no polling. Verify hours before visiting.
- 2026-09-07: Riot Merch retailer (item 5). New tcgwatch/retailers/riotmerch.py,
  plain HTTP against merch.riotgames.com/en-us/product/<slug>/, anchors on
  the page's own analytics pageview block to avoid grabbing a related
  product's price/availability by mistake. 4 Riftbound Booster Displays
  tracked (Unleashed, Origins, Spiritforged, Vendetta), all confirmed live
  and currently out of stock at $119.99.
- 2026-09-07: Booster box price watch (item 4). New tcgwatch/retailers/
  tcgplayer_price.py, a price-only stub (in_stock=None, never alerts) that
  rides the existing TCGplayer market-price loop. 5 Pokemon booster boxes
  tracked (Chaos Rising, Ascended Heroes, Prismatic Evolutions, Destined
  Rivals, Surging Sparks). GameNerdz deferred: unverified, no probe run
  against it this round.
