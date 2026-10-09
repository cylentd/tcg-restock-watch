# Status

One line per active thread. Update the moment you stop working on something — captured now beats remembered later. Git already answers "what changed and why" (commit messages); this answers "why does it matter" and "what's next", the two things memory drops first.

This repo also keeps a detailed roadmap at [docs/ROADMAP.md](../ROADMAP.md) — this file is the short "what's active" summary, that one is the full plan.

| Thread | Branch | Status | Next action | Touched |
|---|---|---|---|---|
| Test backlog (validator pass 2026-10-06, 8 minors) | — | open | Record real retailer answers to replace the hand-built `tests/fixtures/`; move `read_walmart_page` into `tests/builders.py`; parametrize the two @everyone tests; tidy `test_bestbuy_midpass_recycle.py` (private call, `object.__new__`); restore `Browser._daemon_ready` via monkeypatch; layer markers; a 10x / random-order run; mutation survivors (2026-10-06, 15 mutants each): retailers/walmart.py 100% (32/32 killed, 0 survive, `tests/test_walmart_parser.py`, 2026-10-06; was 13% on the first 15-mutant sample), mutation survivors, 20-mutant samples per module: lifecycle.py 50% → 85% (2026-10-09; survivors: set-phrase cap 3, buzz cap 8, exact-60-day `>`), msrp.py 35% → 85% (survivors: lru cache size, 0.005 fee epsilon, 2% label tolerance), feeds.py 35% → 85% (survivors: 120-char log cut, exact-7-day `<`, 140-char title cut); the survivors are undocumented constants or exact-boundary cases the README does not state | 2026-10-09 |

## Closed (last 5)

Move a row here when a thread lands. Trim past 5 — git log is the permanent record, this is a working memory aid, not an archive.

| Price-history/EV/MSRP/sparkline trunk | market-thread (merged) | landed 2026-09-08 | — | 2026-09-08 |
| Pokemon Center + Sam's Club JSON-LD polling | finish-jsonld-stock (merged) | landed 2026-09-08, live-verified | — | 2026-09-08 |
