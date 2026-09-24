"""Unit tests for Browser's memory-based recycle logic (tcgwatch/browser.py).

No real agent-browser process or Chrome is involved: shutil.which is monkeypatched so
Browser() can be constructed, and memory_mb() is monkeypatched directly so these tests
pin the cap arithmetic, not psutil's behavior.
"""

from __future__ import annotations

import time

import pytest

from tcgwatch import browser as browser_mod
from tcgwatch.browser import Browser


@pytest.fixture
def fake_browser(monkeypatch):
    monkeypatch.setattr(browser_mod.shutil, "which", lambda name: "C:/fake/agent-browser.cmd")
    b = Browser(chrome_path="C:/fake/chrome.exe", profile_dir="C:/fake/profile")
    Browser._daemon_ready = True
    yield b
    Browser._daemon_ready = False


def test_chrome_cap_is_2000_mb():
    assert browser_mod.CHROME_CAP_MB == 2000


def test_over_memory_cap_none_when_under_both_caps(fake_browser, monkeypatch):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (100, 500))
    assert fake_browser.over_memory_cap() is None


def test_over_memory_cap_fires_on_chrome_cap(fake_browser, monkeypatch):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (100, browser_mod.CHROME_CAP_MB + 1))
    reason = fake_browser.over_memory_cap()
    assert reason is not None
    assert "chrome" in reason


def test_over_memory_cap_fires_on_daemon_cap(fake_browser, monkeypatch):
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (browser_mod.DAEMON_CAP_MB + 1, 100))
    reason = fake_browser.over_memory_cap()
    assert reason is not None
    assert "daemon" in reason


def test_over_memory_cap_exactly_at_cap_does_not_fire(fake_browser, monkeypatch):
    # The cap is a "more than" boundary, not "at least".
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (browser_mod.DAEMON_CAP_MB, browser_mod.CHROME_CAP_MB))
    assert fake_browser.over_memory_cap() is None


def test_over_memory_cap_none_before_daemon_ready(fake_browser, monkeypatch):
    Browser._daemon_ready = False
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (999999, 999999))
    assert fake_browser.over_memory_cap() is None


def test_due_for_recycle_delegates_to_memory_cap(fake_browser, monkeypatch):
    fake_browser.launched = time.time()
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (100, browser_mod.CHROME_CAP_MB + 1))
    reason = fake_browser.due_for_recycle()
    assert reason is not None
    assert "chrome" in reason


def test_due_for_recycle_age_wins_even_under_cap(fake_browser, monkeypatch):
    fake_browser.launched = time.time() - browser_mod.RECYCLE_AFTER_S - 1
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (0, 0))
    assert fake_browser.due_for_recycle() == "age"


def test_due_for_recycle_none_when_fresh_and_under_cap(fake_browser, monkeypatch):
    fake_browser.launched = time.time()
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (0, 0))
    assert fake_browser.due_for_recycle() is None
