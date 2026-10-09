"""`watch.py --market-only`: only the TCGplayer market tick and the daily history append run.

Oracle: README "Market prices only". The mode runs the market tick (one product per tick, cached a day)
and the history append forever, for the hot products only, with no retailer polls, no Reddit feeds, no
browser, no alerts and no site deploy. The scheduled task for it ("TCG Market Prices") is separate from
"TCG Restock Watch" and is windowless.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

import watch
from tcgwatch import history
from tcgwatch import watcher as watcher_mod
from tcgwatch.config import Product
from tests.builders import make_config, make_watcher

ROOT = Path(__file__).resolve().parent.parent
HIT = {"market": 12.5, "name": "Prismatic Evolutions Elite Trainer Box", "product_id": 1}


class StopLoop(Exception):
    pass


def _market_watcher(tmp_path, monkeypatch, sleeps_allowed=2):
    """A watcher with one product whose every non-market entry point raises if touched."""
    product = Product(retailer="target", id="1", name="Pokemon Prismatic Evolutions Elite Trainer Box", msrp=49.99)
    w = make_watcher(tmp_path, products=[product])
    forbidden = []

    def boom(name):
        def _raise(*a, **k):
            forbidden.append(name)
            raise AssertionError(f"{name} must not run in --market-only")
        return _raise

    for name in ("poll_due", "run_feeds", "run_retailer", "run_direct_loop", "alert", "maybe_deploy_site",
                 "run_once", "get_browser"):
        monkeypatch.setattr(w, name, boom(name))
    searches = []

    def fake_search(query, game, pin=None):
        searches.append(query)
        return dict(HIT)

    monkeypatch.setattr(watcher_mod.market_mod, "search", fake_search)
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= sleeps_allowed:
            raise StopLoop

    monkeypatch.setattr(watcher_mod.time, "sleep", fake_sleep)
    return w, searches, sleeps, forbidden


def test_market_only_runs_the_tick_and_appends_history_once_per_day(tmp_path, monkeypatch):
    w, searches, sleeps, forbidden = _market_watcher(tmp_path, monkeypatch, sleeps_allowed=2)

    with pytest.raises(StopLoop):
        w.run_market_only()

    # Tick 1 priced the one product; tick 2 is inside the 86400 s cache, so no second lookup.
    assert len(searches) == 1
    series = history.read_all(tmp_path)
    assert list(series.values()) == [{"2027-01-15": 12.5}]
    assert len(sleeps) == 2
    assert forbidden == []


def test_market_only_sleeps_the_market_interval_between_ticks(tmp_path, monkeypatch):
    w, _, sleeps, _ = _market_watcher(tmp_path, monkeypatch, sleeps_allowed=1)

    with pytest.raises(StopLoop):
        w.run_market_only()

    # market_interval x uniform(0.9, 1.3), the same pacing the full watcher's market thread uses.
    interval = w.cfg.market_interval
    assert interval * 0.9 <= sleeps[0] <= interval * 1.3


def test_market_only_logs_the_number_of_hot_products_it_will_price(tmp_path, monkeypatch, caplog):
    w, _, _, _ = _market_watcher(tmp_path, monkeypatch, sleeps_allowed=1)
    w.cfg.products.append(Product(retailer="target", id="2", name="Pokemon Old Set Tin"))  # a tin is never hot
    caplog.set_level(logging.INFO, logger="tcgwatch")

    with pytest.raises(StopLoop):
        w.run_market_only()

    interval = w.cfg.market_interval
    assert f"market-only: pricing 1 products, one every ~{interval}s, no retailer polls" in caplog.text


def test_market_only_starts_no_threads(tmp_path, monkeypatch):
    w, _, _, _ = _market_watcher(tmp_path, monkeypatch, sleeps_allowed=1)
    started = []
    monkeypatch.setattr(watcher_mod.threading.Thread, "start", lambda self: started.append(self.name))

    with pytest.raises(StopLoop):
        w.run_market_only()

    assert started == []


class RecordingWatcher:
    """Stands in for Watcher inside watch.main: records which entry point main chose."""

    calls: list[str] = []

    def __init__(self, cfg):
        self.cfg = cfg

    def run_market_only(self):
        RecordingWatcher.calls.append("market_only")

    def run_forever(self):
        RecordingWatcher.calls.append("forever")

    def run_once(self):
        RecordingWatcher.calls.append("once")


def test_main_flag_routes_to_market_only_without_a_browser(tmp_path, monkeypatch):
    cfg = make_config(tmp_path, products=[Product(retailer="target", id="1", name="Pokemon ETB")])
    RecordingWatcher.calls = []
    monkeypatch.setattr(watch.config_mod, "load", lambda path: cfg)
    monkeypatch.setattr(watch, "setup_logging", lambda data_dir, verbose: None)
    monkeypatch.setattr(watch, "Watcher", RecordingWatcher)

    def no_browser(*a, **k):
        raise AssertionError("--market-only must not construct a Browser")

    monkeypatch.setattr(watch, "Browser", no_browser)
    monkeypatch.setattr(sys, "argv", ["watch.py", "--market-only"])

    assert watch.main() == 0
    assert RecordingWatcher.calls == ["market_only"]


def test_main_market_only_with_no_products_exits_2(tmp_path, monkeypatch, capsys):
    cfg = make_config(tmp_path, products=[])
    RecordingWatcher.calls = []
    monkeypatch.setattr(watch.config_mod, "load", lambda path: cfg)
    monkeypatch.setattr(watch, "setup_logging", lambda data_dir, verbose: None)
    monkeypatch.setattr(watch, "Watcher", RecordingWatcher)
    monkeypatch.setattr(sys, "argv", ["watch.py", "--market-only"])

    assert watch.main() == 2
    assert RecordingWatcher.calls == []
    assert "no products" in capsys.readouterr().out


def test_install_script_registers_a_separate_windowless_market_task():
    text = (ROOT / "scripts" / "install-task.ps1").read_text(encoding="utf-8")

    assert "[switch]$MarketOnly" in text
    assert '"TCG Market Prices"' in text
    assert "--market-only" in text
    assert "pythonw.exe" in text  # windowless interpreter, as the existing task
    # The market branch must not enable, disable, start or register the restock task.
    market_branch = text.split("if ($MarketOnly)", 1)[1].split("exit", 1)[0]
    assert "TCG Restock Watch" not in market_branch
