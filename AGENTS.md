# tcg-restock-watch: agent notes

A restock poller that runs all day as the scheduled task "TCG Restock Watch" and alerts on Discord. `README.md` has the retailers, the price rules and the status page; `docs/projects/STATUS.md` has what is active.

## Live hosts: the poller pays for your probes

- Never probe Target, TCGplayer or any retailer while the watcher runs. A burst earns this IP a 403 captcha for every tool on the machine (Target redsky: ~10 searches in a minute, 10+ min block).
- Before any real-browser or live-host test: `Stop-ScheduledTask "TCG Restock Watch"`; after: `Start-ScheduledTask "TCG Restock Watch"`.
- `agent-browser --session tcg close --all` stops the watcher's daemon and every other agent-browser session too.

## Git

Default branch is `master`. Worktree per feature from `origin/master`; finish with `git land master` (a bare `git land` fails: it looks for a remote ref `main`). The conductor lands code without asking, within the conductor skill's hard limits (David, 2026-10-09).

Deploy the status page with `python C:\Users\David\Github\tcg-restock-watch\watch.py --site --deploy`, in exactly that form, because the settings allow rule matches it. Deploy after any land that changes the page.

## Testing

TDD is the default; standards live in the `testing` skill.

| Do | Run |
|---|---|
| One test | `python -m pytest tests/test_browser_recycle.py::test_chrome_cap_is_2000_mb` |
| One file | `python -m pytest tests/test_browser_recycle.py` |
| While working | `python -m pytest -x` |
| Full suite | `python -m pytest` |
| Before land | `python $HOME/.agents/skills/testing/scripts/land_gate.py --base origin/master`, then `git land master` |
| Mutation score | `python $HOME/.agents/skills/testing/scripts/mutate.py --base origin/master` |

- **No live hosts, no real clock in tests.** `tests/conftest.py` blocks every socket, subprocess and curl_cffi call and freezes time; a test that needs a retailer's answer reads a recorded fixture from `tests/fixtures/`.
- **Mutation survivors** go to `docs/projects/STATUS.md` "Test backlog"; `.testing.json` limits mutation to `tcgwatch/**/*.py`.
- **Layers:** pure rules (retire, price verdict, hot score, grouping, alerts) as unit tests; browser-facing code with a fake browser (`test_browser_recycle.py`), never a real Chrome.
- **Oracle:** `README.md` states the rules (Price sanity, Hot first, retire days, alert text). Expected values come from it or are worked out by hand, never from running the code.
- **Exemplars:** `test_hot_score.py` (each expected value worked by hand in a comment, time injected, the README's own battle-deck example); `test_price_verdict.py` (pure, parametrized, hand-worked 1.10x boundaries).
- **Building blocks:** `tests/conftest.py` (blocks sockets, subprocess and curl_cffi; the autouse `clock` with `.advance()`); `tests/builders.py` (`make_config`, `make_watcher`, the fake browsers); `tests/fixtures/` (retailer payloads, hand-built in the real shape until a recorded answer replaces them).
