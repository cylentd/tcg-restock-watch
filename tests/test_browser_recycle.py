"""Unit tests for Browser's memory-based recycle logic (tcgwatch/browser.py).

Oracle (README "Known limits"): the watcher "restarts its Chrome every 6 hours or past 2 GB (checked
after each Best Buy tab close too), and kills the daemon past 1.5 GB". The caps below are those
numbers as literals, not read back from browser_mod, so a changed constant fails here. "Past" means
more than the cap: a reading exactly at the cap does not fire. The README's "2 GB" is read as the
code's 2000 MB. One test per cap pins the constant to the README value.

No real agent-browser process or Chrome is involved: shutil.which is monkeypatched so
Browser() can be constructed, and memory_mb() is monkeypatched directly so these tests
pin the cap arithmetic, not psutil's behavior.
"""

from __future__ import annotations

import pytest

from tcgwatch import browser as browser_mod
from tcgwatch.browser import Browser

# README "Known limits": "past 1.5 GB" (daemon), "past 2 GB" (Chrome), "every 6 hours".
DAEMON_CAP_MB = 1500
CHROME_CAP_MB = 2000
RECYCLE_EVERY_S = 6 * 3600  # 21600


@pytest.fixture
def fake_browser(monkeypatch):
    monkeypatch.setattr(browser_mod.shutil, "which", lambda name: "C:/fake/agent-browser.cmd")
    b = Browser(chrome_path="C:/fake/chrome.exe", profile_dir="C:/fake/profile")
    Browser._daemon_ready = True
    yield b
    Browser._daemon_ready = False


def test_chrome_cap_is_2000_mb():
    assert browser_mod.CHROME_CAP_MB == CHROME_CAP_MB


def test_daemon_cap_is_1500_mb():
    assert browser_mod.DAEMON_CAP_MB == DAEMON_CAP_MB


def test_recycle_interval_is_6_hours():
    assert browser_mod.RECYCLE_AFTER_S == RECYCLE_EVERY_S


# -- over_memory_cap: daemon_mb and chrome_mb readings ------------------------------------------


@pytest.mark.parametrize(
    "daemon_mb, chrome_mb",
    [(100, 500), (DAEMON_CAP_MB, CHROME_CAP_MB), (DAEMON_CAP_MB - 1, CHROME_CAP_MB - 1)],
    ids=["well-under", "exactly-at-both-caps", "one-under-both-caps"],
)
def test_over_memory_cap_is_none_when_neither_reading_is_past_its_cap(fake_browser, monkeypatch, daemon_mb, chrome_mb):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (daemon_mb, chrome_mb))

    assert fake_browser.over_memory_cap() is None, f"daemon {daemon_mb} MB, chrome {chrome_mb} MB"


def test_over_memory_cap_fires_on_chrome_past_2_gb(fake_browser, monkeypatch):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (100, 2001))

    reason = fake_browser.over_memory_cap()

    assert reason is not None and "chrome" in reason, f"chrome at 2001 MB: reason {reason!r}"


def test_over_memory_cap_fires_on_daemon_past_1_5_gb(fake_browser, monkeypatch):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (1501, 100))

    reason = fake_browser.over_memory_cap()

    assert reason is not None and "daemon" in reason, f"daemon at 1501 MB: reason {reason!r}"


def test_over_memory_cap_none_before_daemon_ready(fake_browser, monkeypatch):
    Browser._daemon_ready = False
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (999999, 999999))

    assert fake_browser.over_memory_cap() is None


# -- due_for_recycle: memory, or age --------------------------------------------------------------


def test_due_for_recycle_when_chrome_is_past_2_gb(fake_browser, monkeypatch, clock):
    fake_browser.launched = clock.now
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (100, 2001))

    reason = fake_browser.due_for_recycle()

    assert reason is not None and "chrome" in reason, f"chrome at 2001 MB: reason {reason!r}"


def test_due_for_recycle_when_launched_more_than_6_hours_ago_even_under_the_caps(fake_browser, monkeypatch, clock):
    fake_browser.launched = clock.now
    clock.advance(RECYCLE_EVERY_S + 1)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (0, 0))

    assert fake_browser.due_for_recycle() == "age"


def test_not_due_for_recycle_just_under_6_hours_and_under_the_caps(fake_browser, monkeypatch, clock):
    fake_browser.launched = clock.now
    clock.advance(RECYCLE_EVERY_S - 1)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (0, 0))

    assert fake_browser.due_for_recycle() is None
