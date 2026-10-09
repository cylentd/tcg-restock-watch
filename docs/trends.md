# Trends rules (journey 5)

Code: `tcgwatch/trends.py` (pure; time is passed in as `today`). Tests: `tests/test_trends.py`. This page is the oracle.

| Constant | Value | Meaning |
|---|---|---|
| `WINDOW_DAYS` | 90 | History window ending at `today` |
| `PEAK_BAND` | 5% | "At the peak" tolerance |
| `MIN_HISTORY_DAYS` | 28 | Fewer days of history = early data |
| `DEAL_RATIO` | 1.10 | Deal ceiling = MSRP x 1.10 (same as `max_price_ratio`) |
| `FAIR_RATIO` | 0.90 | Fair ceiling = market x 0.90 |

## Game index

Per day: `index = 100 x median over the game's products of (price that day / price on the base date)`.

- **Window:** dates from `today - 90 days` through `today`.
- **Base date:** the earliest date in the window across the game's products. A product with no price on the base date is left out.
- **Median:** with two products it is their mean.

Worked example (fixture `price_history_sample.jsonl`, Pokemon, today 2026-09-29):

| Date | A | B | Ratios | Median | Index |
|---|---|---|---|---|---|
| 09-01 (base) | 10 | 20 | 1.0, 1.0 | 1.0 | 100.0 |
| 09-15 | 12 | 20 | 1.2, 1.0 | 1.1 | 110.0 |
| 09-29 | 15 | 25 | 1.5, 1.25 | 1.375 | 137.5 |

## Early data

`history_days` = latest index date minus base date. Under 28 the status is `early data` and there is no peak. Exactly 28 is `ok`. No prices at all is `no data`.

Example: Pokemon above spans 09-01 to 09-29 = 28 days = `ok`. One Piece (09-20 to 09-25) = 5 days = `early data`.

## Peak

Peak = the latest day whose index is at least `max - max x 5%`.

Example: indexes 100, 150, 145, 120. Max 150, floor 142.5. 145 qualifies and is later than 150, so the peak is 145. Index exactly on the floor counts (max 200, floor 190: 190 is in, 189.9 is out). `at_peak` is true when the peak is the latest day.

## Deal bands

- `deal_below = MSRP x 1.10`; `fair_below = market x 0.90`. Unknown MSRP or market gives `None` for that band.
- A typed price is `deal` at or under `deal_below`, else `fair` at or under `fair_below`, else `high`.
- **Precedence: deal wins.** The two ceilings are checked in that order, so a price at or under both is `deal`. Example: `deal_below` 110, `fair_below` 180, price 100 is `deal`, not `fair`. Example: `deal_below` 110, `fair_below` 45, price 44 is `deal`.
- A missing ceiling is skipped: with no MSRP only `fair_below` applies, with no market only `deal_below`, with neither every price is `high`.

Example: MSRP 49.99, market 80. `deal_below` 54.989, `fair_below` 72.0. 54.98 is `deal`, 54.99 is `fair` (matches README "Price sanity"), 72.00 is `fair`, 72.01 is `high`.

### What the page prints

Only Python holds rules. `tcgwatch/site_data/trends.py` bakes into each product everything the page shows, and `trends.js` only compares the typed price with `deal_below`, then `fair_below` (`tests/test_section_trends_js.py` runs that comparison under node against the example above).

| Field | Meaning | MSRP 49.99, market 80 |
|---|---|---|
| `deal_shown`, `fair_shown` | Each ceiling rounded **down** to the cent, so the printed price still gets its verdict | 54.98, 72.0 |
| `fair_line` | The fair ceiling gets its own line only when it is above the deal ceiling | true |
| `high_band`, `high_shown` | The ceiling a `high` price is over: the larger one (`fair` when equal) | `fair`, 72.0 |

With market 50 instead, `fair_below` is 45.0, under `deal_below`: `fair_line` is false and a `high` price is over the deal ceiling, `high_band` `deal`, `high_shown` 54.98.

## Distance from the high

Per game: `below_high = (max - latest) / max x 100`, rounded to one digit, where `max` is the highest index in the window and `latest` the newest. `None` under early data or with no data. The card prints it as "N% under its 90-day high" whenever it is above 0, so a card "At 90-day peak" that also reads "-1.5% since Sep 6" shows how far it sits from the top. Example: indexes 100, 200, 197. Max 200, latest 197, `below_high` 1.5. The peak band (5%) still calls it at the peak.

## Sparkline

Display only, in `trends.js` (2026-10-09). It plots the whole 90-day index; points sit at their date.

- **Y range:** the line's own min and max, widened to at least 4 index points around their middle, then padded by 10% of the span each side. Never anchored at 0. Example: 100, 110, 137.5 gives 96.25 to 141.25.
- **Reference:** a dashed line at the base date (index 100), where the "since" number counts from.

## Drop risk

A product is at risk when `config.yaml` `releases:` has an entry that:

1. has `kind: reprint` (no `kind` means no reprint, no risk),
2. has the same game as the product,
3. has a name that appears in the product name (case and punctuation ignored),
4. has `date` on or after `today`.

With several, the earliest wins. Result: `{release, date}`, else `None`.

Example: release "Mega Evolution: Delta Reign", 2026-11-06, `kind: reprint`. Product "Pokemon Mega Evolution Delta Reign Booster Bundle" is at risk. As of 2026-10-09 no entry in `config.yaml` has `kind`, so nothing is at risk until one is added.
