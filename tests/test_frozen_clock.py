"""The conftest `clock` guard holds: every way tcgwatch reads the time returns the frozen instant.

A test that let the real clock through would pass today and fail on another day, and it would put
today's date into the page and the alert text. One test per way of reading the time. Each reads
the name through a tcgwatch module (site, watcher, history, lifecycle), the way the product code
does, and compares with CLOCK_START or with an hour-and-minute value worked out by hand.

CLOCK_START is 1_800_000_000 s = 20833 days and 8 h after 1970-01-01 = 2027-01-15 08:00:00 UTC.
Local-time readers are compared as timestamps, so the answers do not depend on this machine's timezone.
"""
import datetime as real_datetime
import time as real_time

from tcgwatch import history, lifecycle, site as site_mod, watcher as watcher_mod
from tests.builders import make_config
from tests.conftest import CLOCK_START

DAY = 86_400
ISO_SECONDS = "%Y-%m-%d %H:%M:%S"


# -- time.time ------------------------------------------------------------------------------


def test_time_time_in_tcgwatch_returns_the_frozen_instant():
    assert lifecycle.time.time() == CLOCK_START


def test_time_time_moves_only_when_the_clock_advances(clock):
    clock.advance(90)

    assert lifecycle.time.time() == CLOCK_START + 90


def test_sleep_and_perf_counter_stay_real():
    assert watcher_mod.time.sleep is real_time.sleep
    assert watcher_mod.time.perf_counter is real_time.perf_counter


# -- time.strftime, localtime, gmtime with no argument ---------------------------------------------


def test_strftime_without_a_time_formats_the_frozen_instant():
    text = watcher_mod.time.strftime(ISO_SECONDS)

    assert real_datetime.datetime.strptime(text, ISO_SECONDS).timestamp() == CLOCK_START, f"formatted {text!r}"


def test_strftime_moves_with_the_clock(clock):
    clock.advance(DAY)

    text = watcher_mod.time.strftime(ISO_SECONDS)

    assert real_datetime.datetime.strptime(text, ISO_SECONDS).timestamp() == CLOCK_START + DAY


def test_strftime_given_its_own_time_formats_that_time():
    assert watcher_mod.time.strftime("%Y", real_time.gmtime(0)) == "1970"


def test_gmtime_without_an_argument_is_the_frozen_instant_in_utc():
    now = watcher_mod.time.gmtime()

    assert (now.tm_year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min) == (2027, 1, 15, 8, 0)


def test_localtime_without_an_argument_is_the_frozen_instant():
    assert real_time.mktime(watcher_mod.time.localtime()) == CLOCK_START


# -- datetime.now, utcnow and date.today ---------------------------------------------------


def test_datetime_now_is_the_frozen_instant():
    assert site_mod.datetime.now().timestamp() == CLOCK_START


def test_datetime_now_moves_with_the_clock(clock):
    clock.advance(3_600)

    assert site_mod.datetime.now().timestamp() == CLOCK_START + 3_600


def test_datetime_utcnow_is_the_frozen_instant_in_utc():
    assert history.datetime.utcnow() == real_datetime.datetime(2027, 1, 15, 8, 0, 0)


def test_date_today_is_the_frozen_day_and_moves_with_the_clock(clock):
    frozen_day = real_datetime.date.fromtimestamp(CLOCK_START)
    assert history.date_cls.today() == frozen_day
    clock.advance(2 * DAY)

    assert history.date_cls.today() == frozen_day + real_datetime.timedelta(days=2)


# -- through the product code: the page's own clock reads --------------------------------------


def test_status_page_stamps_the_frozen_instant_in_its_data(tmp_path):
    page = site_mod.collect(make_config(tmp_path))

    label_time = real_datetime.datetime.strptime("2027 " + page["generated_label"], "%Y %b %d, %H:%M")
    assert page["generated"] == CLOCK_START
    assert label_time.timestamp() == CLOCK_START, f"label {page['generated_label']!r}"


def test_release_countdown_counts_from_the_frozen_day(tmp_path):
    release = {"game": "Pokemon", "name": "Test Set", "date": "2027-01-20"}
    frozen_day = real_datetime.date.fromtimestamp(CLOCK_START)

    page = site_mod.collect(make_config(tmp_path, releases=[release]))

    assert [r["days"] for r in page["releases"]] == [(real_datetime.date(2027, 1, 20) - frozen_day).days]
