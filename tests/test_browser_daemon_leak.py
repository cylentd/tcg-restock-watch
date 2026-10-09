"""Daemon leak (ledger #47, 2026-10-08): the agent-browser daemon reached ~2.5 GB private memory in ~5 h
while the recycle never killed it.

Cause pinned here: the caps read resident set size (RSS), which Windows trims for an idle daemon, so the
daemon's 1500 MB cap never tripped while its private (committed) memory kept growing. Oracle: the caps
compare private bytes; and 2000 browser commands since launch recycles regardless of memory. A recycle
that fires for the command count restarts the daemon too, so memory cannot grow without bound.
(A combined daemon+Chrome cap was dropped: the frozen caps already allow 1500+2000, so it could not fire.)

No real agent-browser or Chrome: psutil lookups, kills and the subprocess are faked.
"""

from __future__ import annotations

import types

import pytest

from tcgwatch import browser as browser_mod
from tcgwatch.browser import Browser

MB = 1024 * 1024
COMMANDS_BACKSTOP = 2000


@pytest.fixture
def fake_browser(monkeypatch):
    monkeypatch.setattr(browser_mod.shutil, "which", lambda name: "C:/fake/agent-browser.cmd")
    b = Browser(chrome_path="C:/fake/chrome.exe", profile_dir="C:/fake/profile")
    Browser._daemon_ready = True
    yield b
    Browser._daemon_ready = False


class FakePopen:
    spawned = 0

    def __init__(self, cmd, **kwargs):
        FakePopen.spawned += 1
        self.returncode = 0

    def communicate(self, timeout=None):
        return "", ""


def _proc(rss_mb: int, private_mb: int):
    mem = types.SimpleNamespace(rss=rss_mb * MB, private=private_mb * MB)
    return types.SimpleNamespace(info={"memory_info": mem})


def test_command_backstop_is_2000():
    assert browser_mod.RECYCLE_AFTER_COMMANDS == COMMANDS_BACKSTOP


def test_memory_mb_reads_private_bytes_not_rss(fake_browser, monkeypatch):
    # Daemon paged out: 120 MB resident, 2500 MB private (the 2026-10-08 reading). Chrome 300 / 400.
    monkeypatch.setattr(
        browser_mod, "_procs", lambda name, cmd=None: [_proc(120, 2500)] if name == browser_mod.DAEMON_EXE else [_proc(300, 400)]
    )

    assert fake_browser.memory_mb() == (2500, 400)


def test_over_memory_cap_fires_after_2000_commands_with_memory_flat(fake_browser, monkeypatch):
    monkeypatch.setattr(browser_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (10, 10))
    for _ in range(COMMANDS_BACKSTOP):
        fake_browser.run("get", "url", check=False)
    assert fake_browser.over_memory_cap() is None, "2000 commands is the limit, not past it"

    fake_browser.run("get", "url", check=False)

    reason = fake_browser.over_memory_cap()
    assert reason is not None and "commands" in reason, f"2001 commands: reason {reason!r}"


def _recycle_killed(fake_browser, monkeypatch, reason, memory):
    killed = []
    monkeypatch.setattr(browser_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: memory)
    monkeypatch.setattr(browser_mod, "_procs", lambda name, cmd=None: [name])
    monkeypatch.setattr(browser_mod, "_kill", lambda procs, what: killed.append(what) or len(procs))
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)
    fake_browser.recycle(reason)
    return killed


def test_recycle_kills_the_daemon_when_its_private_memory_is_past_the_cap(fake_browser, monkeypatch):
    killed = _recycle_killed(fake_browser, monkeypatch, "daemon 1501 MB", (1501, 10))

    assert "agent-browser daemon" in killed


def test_recycle_spares_the_daemon_at_exactly_the_cap(fake_browser, monkeypatch):
    killed = _recycle_killed(fake_browser, monkeypatch, "chrome 2001 MB", (1500, 2001))

    assert "agent-browser daemon" not in killed


def test_commands_recycle_with_daemon_under_cap_spares_the_shared_daemon(fake_browser, monkeypatch):
    killed = _recycle_killed(fake_browser, monkeypatch, "commands 2001", (10, 10))

    assert killed == ["orphaned watcher Chrome"], "only this session's Chrome is closed"


def test_recycle_for_age_leaves_the_shared_daemon_alone(fake_browser, monkeypatch):
    killed = []
    monkeypatch.setattr(browser_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (10, 10))
    monkeypatch.setattr(browser_mod, "_procs", lambda name, cmd=None: [name])
    monkeypatch.setattr(browser_mod, "_kill", lambda procs, what: killed.append(what) or len(procs))

    fake_browser.recycle("age")

    assert "agent-browser daemon" not in killed


def test_recycle_resets_the_command_count(fake_browser, monkeypatch):
    monkeypatch.setattr(browser_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(fake_browser, "memory_mb", lambda: (10, 10))
    monkeypatch.setattr(browser_mod, "_procs", lambda name, cmd=None: [])
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)
    for _ in range(COMMANDS_BACKSTOP + 5):
        fake_browser.run("get", "url", check=False)

    fake_browser.recycle("commands 2005")

    assert fake_browser.commands == 0, "a fresh session has run no commands"
