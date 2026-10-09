# Vision

Where tcg-restock-watch is going. Conductors read this before sizing work here and append dated decisions. David edits it freely.

## Direction

- Catch retailer restocks at MSRP before they sell out: a phone alert within a poll interval, page already open on the PC.
- Market price is what you pay if you miss the drop; every price shown is judged against MSRP.
- Runs unattended all day on this PC, so it must stay light: flat memory, no host bursts, never block the machine's other work.
- Site direction: open, being brainstormed (2026-10-09).

## Decisions

- 2026-09-07: retailer marketplace listings count as out of stock, so an alert always means the retailer sells at its own price.
- 2026-09-08: abandoned the tcgcsv.com backfill after three WAF blocks (David's call); daily history appends from the market tick instead.
- 2026-10-09: added a per-scanner audit to TODO, to find where each scanner can improve (David).

## Not doing

- Polling Pokemon Center: Imperva blocks automated browsers; the Reddit feeds cover its drops.
- Routine production traffic to tcgcsv.com.
