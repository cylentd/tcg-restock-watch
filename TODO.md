# TODO

Ranked. The conductor picks from the top; `(conductor)` and `(suggested)` mark items an agent added. Done items leave this file; git log keeps them. The full history of earlier work is in `docs/ROADMAP.md`.

## Now

- **Browser daemon leak** (ledger #47). The `tcg` agent-browser daemon grows to ~2.5 GB private over ~5 h and starves loadgate. Recycle the daemon on a memory cap and every N checks, then confirm RAM stays flat for a day after it lands. Branch `browser-leak`.
- **Mutation survivors.** lifecycle.py 33%, msrp.py 40%, feeds.py 47% (2026-10-06 samples). Branch `mutation-survivors`.

## Next

- **Audit every scanner, list where each can improve.** One pass per retailer module (`tcgwatch/retailers/*`, plus the Reddit feeds and the TCGplayer market tick). For each: how it checks stock, interval, failure modes seen in the logs (403s, captchas, timeouts, false in-stock), memory and time per pass, test and mutation coverage, and ranked improvements with a size each. Read-only on code and logs; no live-host probes without the poller stopped first (AGENTS.md). Output: `docs/scanner-audit.md`, then its improvements come back here as `(suggested)` items. (David, 2026-10-09)
- **Site direction.** Brainstormed 2026-10-09; David's pick goes into `VISION.md` Direction, then the build is planned from it.
- **Test backlog** from the 2026-10-06 validator pass: recorded retailer fixtures to replace hand-built ones, `read_walmart_page` into `tests/builders.py`, parametrize the two @everyone tests, tidy `test_bestbuy_midpass_recycle.py`, restore `Browser._daemon_ready` via monkeypatch, layer markers, a 10x random-order run. Detail in `docs/projects/STATUS.md`.

## Later

- **Verify the 6 shipping numbers** in `config.yaml` (flagged unverified 2026-09-08) against each retailer. Needs live pages, poller stopped.
- **GameNerdz** booster box prices (deferred 2026-09-07, never probed).

## Parked

- **tcgcsv.com as the price source** for market.py/singles.py. Parked 2026-09-08 after three WAF blocks in one day. Revisit only with a real headless browser that can pass a JS challenge.
