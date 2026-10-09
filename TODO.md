# TODO

Ranked. The conductor picks from the top; `(conductor)` and `(suggested)` mark items an agent added. Done items leave this file; git log keeps them. The full history of earlier work is in `docs/ROADMAP.md`.

## Now

- **Browser daemon leak** (ledger #47). The `tcg` agent-browser daemon grows to ~2.5 GB private over ~5 h and starves loadgate. Fix ready on branch `browser-leak` (b5963ca), waiting on David's "land it". After landing, restart the scheduled task and confirm RAM stays flat for a day. After landing, read the watcher log a day later to see how often the 2000-command recycle (`RECYCLE_AFTER_COMMANDS`, a guess) fires, and tune it.

## Next

- **Mutation follow-up** (suggested, feature). (1) Fix the exact boundaries in README: retire at exactly 60 days (lifecycle.py:106 `>` vs `>=`) and the 7-day cut (feeds.py:209 `<` vs `<=`), then add the two boundary tests that kill those survivors. (2) Move the caps (buzz 8, set phrase 3, title 140, log 120) into the module constants file as named constants with a source comment. (3) Mark msrp.py:34 (lru_cache size) and msrp.py:75 (0.005 fee epsilon) `nomutate:` with the equivalence reason. (4) Run mutation in full once; the 2026-10-09 score is a 20-per-module sample of 188 mutants.
- **Audit every scanner, list where each can improve.** One pass per retailer module (`tcgwatch/retailers/*`, plus the Reddit feeds and the TCGplayer market tick). For each: how it checks stock, interval, failure modes seen in the logs (403s, captchas, timeouts, false in-stock), memory and time per pass, test and mutation coverage, and ranked improvements with a size each. Read-only on code and logs; no live-host probes without the poller stopped first (AGENTS.md). Output: `docs/scanner-audit.md`, then its improvements come back here as `(suggested)` items. (David, 2026-10-09)
- **Site direction.** Brainstormed 2026-10-09; David's pick goes into `VISION.md` Direction, then the build is planned from it.
- **Test backlog** from the 2026-10-06 validator pass: recorded retailer fixtures to replace hand-built ones, `read_walmart_page` into `tests/builders.py`, parametrize the two @everyone tests, tidy `test_bestbuy_midpass_recycle.py`, restore `Browser._daemon_ready` via monkeypatch, layer markers, a 10x random-order run. Detail in `docs/projects/STATUS.md`.

## Later

- **Verify the 6 shipping numbers** in `config.yaml` (flagged unverified 2026-09-08) against each retailer. Needs live pages, poller stopped.
- **GameNerdz** booster box prices (deferred 2026-09-07, never probed).

## Parked

- **tcgcsv.com as the price source** for market.py/singles.py. Parked 2026-09-08 after three WAF blocks in one day. Revisit only with a real headless browser that can pass a JS challenge.
