# tcg-restock-watch

Phone alert the moment a Pokemon, One Piece or Riftbound TCG product comes back in stock online, with the item already in your cart. Free stack: Python, agent-browser, a Discord webhook.

## Setup (10 minutes)

1. In Discord, create a private server with a `#drops` channel. Channel settings > Integrations > Webhooks > New Webhook > Copy Webhook URL. Paste it into `config.yaml` under `discord_webhook`. In the Discord mobile app, set that channel's notifications to All Messages.
2. Run `python watch.py --test`. A message should land in `#drops` and buzz your phone.
3. Make sure you are signed in to Target, Best Buy, and Walmart in your normal browser. That is where drops open.
4. Optional: get a free key at developer.bestbuy.com and paste it into `config.local.yaml` as `bestbuy_api_key`. Without it Best Buy is checked by loading pages in the background browser, which is slower.
5. Add products to `config.yaml`. Confirm each ID first:

```
python watch.py --lookup target 93954446
```

6. Run `python watch.py`. To start it at every logon: `powershell -ExecutionPolicy Bypass -File scripts\install-task.ps1`.

## What it does per retailer

| Retailer | Stock check | Interval | Needs background browser |
|---|---|---|---|
| Target | JSON endpoint, one request for all TCINs, Target Plus marketplace sellers ignored | 90 s | No |
| Best Buy | Official API by SKU, or page check without a key; marketplace sellers ignored | 60 s | Only without an API key |
| Walmart | Loads product page in the background browser, reads embedded JSON, marketplace sellers ignored | 300 s | Yes |
| GameStop | Product JSON endpoint over plain HTTP via `curl_cffi` (Chrome TLS impersonation; GameStop 403s Python's own TLS), one item per request; no marketplace on these pages; store-only pre-orders count as out of stock | 120 s | No |
| Pokemon Center | Not pollable: Imperva blocks automated browsers outright | n/a | n/a |
| Reddit deal feeds | Atom feed of new posts, keyword match | 120 s | No |

On a drop at an acceptable price the watcher opens the product page in your normal browser (`cart: open`). Your real profile, already signed in, no automation fingerprint. You click Add to cart. The controlled background browser is never something you interact with; the retailers' bot checks flag it no matter who is clicking.

`cart: auto` makes the background browser add the item itself. It worked on Target as a guest in testing but trips press-and-hold checks often enough that it is opt-in.

Pokemon Center drops are covered by the Reddit feeds, where they get posted within minutes. The alert opens the link and you join the queue by hand.

Target, Best Buy, and Walmart all host third-party "marketplace" sellers on the same product pages. Those are where the $349 booster boxes live. The watcher treats a marketplace listing as out of stock, so an alert always means the retailer itself is selling at its own price.

## Price sanity

Each product carries an `msrp`. A listing above `msrp * max_price_ratio` (default 1.10) still alerts but is labeled INFLATED and is not carted. Reference MSRPs live in `tcgwatch/msrp.py`.

## Alerts

Alerts go to the Discord webhook, and also to an ntfy.sh topic if `ntfy_topic` is set.

- **IN STOCK: name** with the price verdict and the store link. Pings @everyone so it breaks through "Mentions only". On the PC the page is already open.
- **Walmart wants a captcha** when the "Robot or human?" page appears. Solve it in the watcher's Chrome window. Sent at most every 30 min.
- **r/subreddit new post** for feed keyword hits.

## Status page

Live at https://tcg-restock-watch.vercel.app. Products are grouped across retailers, with MSRP, TCGplayer market price, the premium between them, and each retailer's last-seen price and status. Filter by game, retailer, status, or search.

`python watch.py --site` builds `site/index.html` from the config and the last poll results; `--deploy` pushes it to Vercel. With `site_deploy: true` the watcher rebuilds and redeploys on its own whenever stock or a price changes, at most every 5 minutes.

## Hot first, stale last

Default sort is "Hottest first". The score is the market premium over MSRP, weighted by product type (booster boxes and premium collections 1.3, ETBs 1.2, blisters and tins 0.8, decks 0.6), boosted by how many times the product's set was mentioned in the deal subreddits this week (the flame count on the row). In stock triples it only when the premium is 1.3× or more; an unpriced or at-MSRP item in stock gets 1.3×, so a battle deck at Walmart does not outrank a scalped ETB. Recently in stock (7 days) is 1.5× or 1.1× on the same rule.

If the TCGplayer name matcher cannot find a product (deck names ending in "[Set of 2]" look like lot listings and are skipped), add `tcgplayer: <product id>` to its config line. The id is the number after `/product/` in the TCGplayer URL.

A product retires when no retailer has had it in stock for `retire_after_days` (60) since first seen, or when every retailer has delisted it for `retire_missing_days` (7). Retired products stop being polled and move to a collapsed section at the bottom of the page. Remove them from `config.yaml` whenever you like.

## Prices

- **MSRP** is set per product in `config.yaml`. Sources: manufacturer list prices (Pokemon $4.49 per pack, $49.99 ETB, $119.99 UPC; One Piece $11.99 starter, $4.99 to $5.99 pack) and the retailer's own list price where it was visible (Target lists current booster bundles at $31.99). A few newer items carry an estimate; a blank MSRP means unknown, and the poll's "seen at" price fills in the retailer's real number.
- **Seen at** is the price the retailer itself showed at the last poll. Target's is fetched one product per poll and refreshed daily; Best Buy and Walmart read it off the page each check. It stays blank until the watcher has polled that product.
- **Market** is TCGplayer's market price for the same sealed product, looked up one product every 45 s and cached for a day. TCGplayer has no public API, so this uses the search endpoint its site calls, gently. A dozen requests in two minutes got a soft block during testing.

The premise of the whole tool: retailer-sold listings are at MSRP, they just sell out in minutes. Market price is what you pay if you miss the drop.

## Finding more products

- Target: `python watch.py --discover "pokemon booster bundle"` prints config entries for items Target sells itself. Do not run it in a burst; a dozen searches in a minute earned a 403 captcha on the whole redsky API for over ten minutes.
- Walmart: search on walmart.com with `&facet=retailer_type%3AWalmart` appended to the URL. That filter shows Walmart's own listings including sold-out ones, which plain search hides. The item ID is the number at the end of the product URL.
- Best Buy: search on bestbuy.com. The SKU is the number after `/sku/` in the product link. Product pages without a numeric SKU can be given as a full `url` in the config.
- GameStop: search on gamestop.com. The item ID is the number before `.html` at the end of the product URL. `python watch.py --lookup gamestop 20036324` confirms it.

## Release calendar

`releases:` in `config.yaml` feeds the "Coming up" section: `{game, name, date: YYYY-MM-DD, note, source}`. Entries stay visible for 14 days after the date as "out now", then drop off. Maintained by hand; add a set as soon as it is announced so the preorder window is not missed.

## Files

- `watch.py` entry point. `--once`, `--test`, `--lookup RETAILER ID`, `--login` (only for `cart: auto`).
- `config.yaml` products, feeds, intervals, topic.
- `~/.tcg-watch/` state, rotating log, Chrome profile.

## Known limits

- The PC must be awake. A scheduled task at logon keeps the watcher running; sleep pauses it.
- Retailer sites change. When a check starts returning `None` for every product, the endpoint or page shape moved. Look at `watch.log`.
- Auto-checkout is deliberately not implemented. It violates retailer terms and gets accounts banned.
