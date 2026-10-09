# Vision

Where tcg-restock-watch is going. Conductors read this before sizing work here and append dated decisions. David edits it freely.

## Direction

- Get sealed product at MSRP, and know when a price is a deal. Most products sit above MSRP, so "in stock" alone means nothing (David, 2026-10-09).
- Five user journeys, in David's words (2026-10-09):
  1. Find restock times for local stores, so users know when to show up in person to buy at MSRP.
  2. Automate buying online on drops: add to cart and buy.
  3. Find every retailer raffle and its time, and alert users. The Reddit scanner may report them.
  4. Track only hot items (booster bundles, ETBs, booster boxes); loose packs are not worth it.
  5. Show market trends per TCG: is this shelf price a deal, is the market at a peak, is a drop coming that will lower prices.
- Runs unattended all day on this PC, so it must stay light: flat memory, no host bursts, never block the machine's other work.

## Decisions

- 2026-09-07: retailer marketplace listings count as out of stock, so an alert always means the retailer sells at its own price.
- 2026-09-08: abandoned the tcgcsv.com backfill after three WAF blocks (David's call); daily history appends from the market tick instead.
- 2026-10-09: added a per-scanner audit to TODO, to find where each scanner can improve (David).
- 2026-10-09: replaced the stock-first site direction with the five journeys above, because "most products are going to be above MSRP. This makes in stock mean nothing." (David)
- 2026-10-09: kept the watcher's scheduled task disabled after the leak fix landed (David).
- 2026-10-09: buy automation stops at the cart and David clicks Buy (1a), over full auto-checkout. Meta Muse research found no sanctioned agent checkout that handles drops or bot checks.
- 2026-10-09: "site is for everyone. buy automation is for me but can be for everyone if it works." (David)
- 2026-10-09: premium collections count as hot items, beside booster bundles, ETBs and booster boxes (David, 3a).
- 2026-10-09: non-hot products stop being polled, not just hidden. Riftbound Vault Bundles and 30th Celebration ex Boxes count as hot; Walmart "booster (bundle or box, verify)" listings, the First Partner Illustration Collection and sticker/poster collections do not (David, "1 a d").
- 2026-10-09: "Is it a deal?" sits at the top of the page, above the product list (David, 2a).
- 2026-10-09: accepted the default deal thresholds: deal at or under MSRP x 1.10, fair under market x 0.90, peak within 5% of the 90-day high, early data under 28 days (David, 2a).
- 2026-10-09: run the TCGplayer market tick on its own while the restock watcher stays off (David, 4a).
- 2026-10-09: trend sparklines fit their own range with a start-value line, over a shorter time window or a smaller chart (David, 1a, after "the graph seems pretty flat"). The shelf-check card keeps one fixed size, and the picker shows product pictures.

## Not doing

- Full auto-checkout: the bot adds to cart, a human clicks Buy (2026-10-09).
- Polling Pokemon Center: Imperva blocks automated browsers; the Reddit feeds cover its drops.
- Routine production traffic to tcgcsv.com.
