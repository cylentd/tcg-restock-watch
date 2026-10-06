"""Shared test setup: no test may reach the network, start a process, or read the real clock.

The watcher polls live retailers all day from this machine, and rate limits count per IP, so a test that
touched Target or TCGplayer would spend the poller's budget (AGENTS.md "Live hosts"). Every socket
connection, every subprocess and every curl_cffi request fails here; a test that needs a retailer's
answer reads a hand-built or recorded file from tests/fixtures/.

Every tcgwatch module reads the time through the `time` module or the `datetime`/`date` classes. The
`clock` fixture (autouse) replaces those names in each of them with one frozen instant: time.time(),
time.strftime/localtime/gmtime with no argument, datetime.now()/utcnow()/today() and date.today().
A test moves it with `clock.advance(seconds)` or `clock.now = ...`; sleep and perf_counter stay real.
"""
import datetime as real_datetime
import importlib
import pkgutil
import socket
import subprocess
import sys
import time as real_time

import pytest

CLOCK_START = 1_800_000_000.0  # 2027-01-15 08:00:00 UTC; any fixed instant would do


class NetworkBlocked(RuntimeError):
    pass


def _refuse(*args, **kwargs):
    raise NetworkBlocked("tests may not open sockets, start processes or call curl_cffi; use a fixture in tests/fixtures/")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    # run(), call(), check_call() and check_output() all start a Popen, so one hook covers them and
    # any `from subprocess import run` bound before this fixture ran.
    monkeypatch.setattr(subprocess.Popen, "__init__", _refuse)
    try:
        from curl_cffi import requests as cffi_requests
    except Exception:  # not installed on this machine: nothing to guard
        return
    for owner, names in (
        (cffi_requests.Session, ("request",)),
        (cffi_requests.AsyncSession, ("request",)),
        (cffi_requests, ("request", "get", "post", "put", "patch", "delete", "head", "options")),
    ):
        for name in names:
            if hasattr(owner, name):
                monkeypatch.setattr(owner, name, _refuse)


class FrozenClock:
    """A clock that only moves when the test says so."""

    def __init__(self, now: float = CLOCK_START):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _TimeModule:
    """Stands in for the `time` module inside tcgwatch.

    time(), and strftime/localtime/gmtime called with no argument, read the frozen instant. A call
    that passes its own time stays real, and so do sleep, perf_counter and the rest.
    """

    def __init__(self, clock: FrozenClock):
        self._clock = clock

    def time(self) -> float:
        return self._clock.time()

    def localtime(self, secs=None):
        return real_time.localtime(self._clock.now if secs is None else secs)

    def gmtime(self, secs=None):
        return real_time.gmtime(self._clock.now if secs is None else secs)

    def strftime(self, fmt, t=None):
        return real_time.strftime(fmt, self.localtime() if t is None else t)

    def __getattr__(self, name):
        return getattr(real_time, name)


def _frozen_date_classes(clock: FrozenClock):
    """A datetime and a date class whose now()/utcnow()/today() read the frozen instant."""

    class FrozenDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock.now, tz)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now)

        @classmethod
        def utcnow(cls):
            return cls.fromtimestamp(clock.now, real_datetime.timezone.utc).replace(tzinfo=None)

    class FrozenDate(real_datetime.date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(clock.now)

    return FrozenDatetime, FrozenDate


class _DatetimeModule:
    """Stands in for `import datetime` inside tcgwatch: frozen datetime and date, the rest real."""

    def __init__(self, frozen_datetime, frozen_date):
        self.datetime = frozen_datetime
        self.date = frozen_date

    def __getattr__(self, name):
        return getattr(real_datetime, name)


def _import_every_tcgwatch_module() -> None:
    import tcgwatch

    for info in pkgutil.walk_packages(tcgwatch.__path__, "tcgwatch."):
        try:
            importlib.import_module(info.name)
        except Exception:  # a module that cannot import fails its own tests, not this fixture
            pass


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    _import_every_tcgwatch_module()
    frozen = FrozenClock()
    frozen_datetime, frozen_date = _frozen_date_classes(frozen)
    stand_ins = {
        id(real_time): _TimeModule(frozen),
        id(real_datetime): _DatetimeModule(frozen_datetime, frozen_date),
        id(real_datetime.datetime): frozen_datetime,
        id(real_datetime.date): frozen_date,
    }
    for name, module in list(sys.modules.items()):
        if name != "tcgwatch" and not name.startswith("tcgwatch."):
            continue
        for attr, value in list(vars(module).items()):
            if id(value) in stand_ins:  # any alias: `import time`, `from datetime import date as date_cls`
                monkeypatch.setattr(module, attr, stand_ins[id(value)])
    return frozen
