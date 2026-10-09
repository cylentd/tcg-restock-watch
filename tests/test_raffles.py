"""Unit tests for the raffle classifier (tcgwatch/raffles.py), journey 3.

Oracle (VISION.md journey 3 / the unit brief): retailers run raffles and invite events, announced in
Reddit deal posts. is_raffle() says whether a post is one; entry_window() reads when entries open and
close, as timezone-aware datetimes anchored on the post time. A user's giveaway and a plain restock
post are not raffles. Every expected instant below is worked out by hand in a comment.

Anchor: posted_at = 2026-10-09 15:00 UTC (a Friday). US daylight time runs 2026-03-08 to 2026-11-01,
so in October PT is UTC-7 and ET is UTC-4; from 2026-11-01 PT is UTC-8 and ET is UTC-5.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tcgwatch import raffles

FIXTURES = Path(__file__).parent / "fixtures"
UTC = timezone.utc
POSTED = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)  # = 1791558000.0, the fixtures' created_utc


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def load_post(name: str) -> dict:
    """First post of a hand-built listing fixture, in the shape feeds._fetch_api reads."""
    listing = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return listing["data"]["children"][0]["data"]


# -- is_raffle ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title, body",
    [
        ("Walmart Pokemon TCG raffle starts today", ""),
        ("Costco lottery for the Pokemon booster bundle", ""),
        ("Request an invite for the Pokemon Center Prismatic collection", ""),
        ("Pokemon Center drawing for the new set, open now", ""),
        ("Target invite event for the Pokemon ETB", ""),           # weak word + retailer + TCG word
        ("Walmart: sign up for the Pokemon booster box drop", ""),  # same shape with "sign up"
        ("Pokemon cards event at Walmart", "Entry opens Oct 12. Enter on their site."),
    ],
)
def test_retailer_raffle_posts_are_raffles(title, body):
    assert raffles.is_raffle(title, body) is True


@pytest.mark.parametrize(
    "title, body",
    [
        ("[GIVEAWAY] I'm giving away 3 Pokemon booster packs", "comment to enter"),
        ("My raffle for r/PokemonTCG members", "I'm hosting it, drawing Sunday"),
        ("Walmart Pokemon ETB back in stock $49.99", "No sign up needed, add to cart"),
        ("Target Pokemon booster bundle restocked, in stock now", "entry level price"),
        ("Sign up for Target Circle to get deals", ""),             # weak word, retailer, no TCG word
        ("Walmart has a sale on drawing tablets", ""),             # "drawing" but no raffle
        ("", ""),
    ],
)
def test_giveaways_restocks_and_chatter_are_not_raffles(title, body):
    assert raffles.is_raffle(title, body) is False


def test_walmart_raffle_fixture_is_a_raffle():
    post = load_post("reddit_raffle_walmart.json")

    assert raffles.is_raffle(post["title"], post["selftext"]) is True


@pytest.mark.parametrize("name", ["reddit_raffle_giveaway.json", "reddit_raffle_restock.json"])
def test_giveaway_and_restock_fixtures_are_not_raffles(name):
    post = load_post(name)

    assert raffles.is_raffle(post["title"], post["selftext"]) is False


# -- entry_window ------------------------------------------------------------------------

def test_fixture_window_reads_both_ends_in_pacific_time():
    post = load_post("reddit_raffle_walmart.json")
    posted = datetime.fromtimestamp(post["created_utc"], UTC)

    window = raffles.entry_window(post["title"], post["selftext"], posted)

    # Oct 12 9:00 PDT (UTC-7) = 16:00 UTC; Oct 14 23:00 PDT = Oct 15 06:00 UTC.
    assert window == (utc(2026, 10, 12, 16, 0), utc(2026, 10, 15, 6, 0))


@pytest.mark.parametrize(
    "text, expected_opens",
    [
        ("Raffle opens Oct 12 9am PT", utc(2026, 10, 12, 16, 0)),            # 9 + 7
        ("Raffle opens October 12th at 9:30 AM PT", utc(2026, 10, 12, 16, 30)),
        ("Raffle opens 10/12 at 12pm ET", utc(2026, 10, 12, 16, 0)),         # noon EDT = 12 + 4
        ("Raffle opens today at 12pm ET", utc(2026, 10, 9, 16, 0)),          # 11:00 EDT on Oct 9 -> today is Oct 9
        ("Raffle opens tomorrow at 10am ET", utc(2026, 10, 10, 14, 0)),      # 10 + 4
        ("Raffle opens Oct 12 12am PT", utc(2026, 10, 12, 7, 0)),            # 12am is hour 0
        ("Raffle opens Oct 12 12pm CT", utc(2026, 10, 12, 17, 0)),           # noon CDT = 12 + 5
        ("Raffle opens Oct 12 9am PST", utc(2026, 10, 12, 17, 0)),           # explicit standard time, 9 + 8
        ("Raffle opens Oct 12 9am UTC", utc(2026, 10, 12, 9, 0)),
    ],
)
def test_open_time_phrasings(text, expected_opens):
    window = raffles.entry_window(text, "", POSTED)

    assert window is not None
    assert window[0] == expected_opens
    assert window[1] is None


def test_until_date_with_no_open_opens_at_the_post_and_closes_end_of_day_eastern():
    window = raffles.entry_window("Walmart raffle open until 10/14", "", POSTED)

    # No time zone given: Eastern. 10/14 23:59:59 EDT = Oct 15 03:59:59 UTC.
    assert window == (POSTED, utc(2026, 10, 15, 3, 59, 59))


@pytest.mark.parametrize("cue", ["until", "through", "ends", "closes", "deadline", "by"])
def test_close_cues(cue):
    window = raffles.entry_window(f"Raffle {cue} Oct 14 11pm PT", "", POSTED)

    # Oct 14 23:00 PDT = Oct 15 06:00 UTC.
    assert window == (POSTED, utc(2026, 10, 15, 6, 0))


def test_range_inherits_the_zone_named_once():
    window = raffles.entry_window("Entries Oct 12 9am - Oct 14 11pm PT", "", POSTED)

    assert window == (utc(2026, 10, 12, 16, 0), utc(2026, 10, 15, 6, 0))


def test_window_is_read_from_the_body_when_the_title_has_none():
    window = raffles.entry_window("Walmart Pokemon raffle", "Opens Oct 12 9am PT.", POSTED)

    assert window == (utc(2026, 10, 12, 16, 0), None)


def test_standard_time_applies_after_the_november_changeover():
    # Nov 2 is after Nov 1 2026 (first Sunday of November): PST, UTC-8. 9am PST = 17:00 UTC.
    posted = utc(2026, 10, 30, 15, 0)

    window = raffles.entry_window("Raffle opens Nov 2 9am PT", "", posted)

    assert window == (utc(2026, 11, 2, 17, 0), None)


def test_a_date_early_in_the_next_year_rolls_the_year_forward():
    posted = utc(2026, 12, 30, 15, 0)

    window = raffles.entry_window("Raffle opens Jan 2 at 9am ET", "", posted)

    # Jan 2 2027 9:00 EST (UTC-5) = 14:00 UTC.
    assert window == (utc(2027, 1, 2, 14, 0), None)


def test_posted_at_may_be_epoch_seconds():
    window = raffles.entry_window("Raffle opens Oct 12 9am PT", "", POSTED.timestamp())

    assert window == (utc(2026, 10, 12, 16, 0), None)


@pytest.mark.parametrize(
    "text",
    [
        "Walmart raffle, details soon",     # no date at all
        "Raffle closes 10/08",              # closes a day before it was posted
        "",
    ],
)
def test_no_usable_window_is_none(text):
    assert raffles.entry_window(text, "", POSTED) is None


@pytest.mark.parametrize(
    "text, posted, expected_opens",
    [
        # A date with no time opens at 00:00 in its zone (module docstring, entry_window rules). A zone
        # is only read next to a time, so the zone here comes from the close's "9am PT".
        ("Raffle opens Oct 12, ends Oct 14 9am PT", POSTED, utc(2026, 10, 12, 7, 0)),   # 00:00 PDT = 07:00 UTC
        ("Raffle opens 10/12, ends 10/14 9am UTC", POSTED, utc(2026, 10, 12, 0, 0)),
        ("Raffle opens Oct 12", POSTED, utc(2026, 10, 12, 4, 0)),           # no zone: Eastern, 00:00 EDT = 04:00 UTC
        # A two-digit year is 20xx; a four-digit year is kept. Oct 2027 is daylight time (Mar 14 - Nov 7).
        ("Raffle opens 10/12/27 9am PT", POSTED, utc(2027, 10, 12, 16, 0)),  # 9 + 7
        ("Raffle opens 10/12/2027 9am PT", POSTED, utc(2027, 10, 12, 16, 0)),
        ("Raffle opens 10/12/26 9am PT", POSTED, utc(2026, 10, 12, 16, 0)),
        # Mountain and Central: generic names follow daylight saving, explicit names never move.
        ("Raffle opens Oct 12 9am MT", POSTED, utc(2026, 10, 12, 15, 0)),    # MDT = UTC-6
        ("Raffle opens Oct 12 9am MDT", POSTED, utc(2026, 10, 12, 15, 0)),
        ("Raffle opens Oct 12 9am MST", POSTED, utc(2026, 10, 12, 16, 0)),   # MST = UTC-7 all year
        ("Raffle opens Oct 12 9am CST", POSTED, utc(2026, 10, 12, 15, 0)),   # CST = UTC-6 all year
        ("Raffle opens Oct 12 9am CDT", POSTED, utc(2026, 10, 12, 14, 0)),   # CDT = UTC-5
        ("Raffle opens Oct 12 9am EST", POSTED, utc(2026, 10, 12, 14, 0)),   # EST = UTC-5 all year
        ("Raffle opens Oct 12 9am EDT", POSTED, utc(2026, 10, 12, 13, 0)),   # EDT = UTC-4
        ("Raffle opens Oct 12 9am PDT", POSTED, utc(2026, 10, 12, 16, 0)),   # PDT = UTC-7
        ("Raffle opens Oct 12 9am GMT", POSTED, utc(2026, 10, 12, 9, 0)),
        ("Raffle opens Jan 12 9am MT", utc(2026, 1, 5, 15, 0), utc(2026, 1, 12, 16, 0)),  # winter MST = UTC-7
        ("Raffle opens Jan 12 9am CT", utc(2026, 1, 5, 15, 0), utc(2026, 1, 12, 15, 0)),  # winter CST = UTC-6
        # Daylight time starts the second Sunday of March: 2026-03-08 (Mar 1 is itself a Sunday).
        ("Raffle opens Mar 7 9am PT", utc(2026, 3, 1, 15, 0), utc(2026, 3, 7, 17, 0)),    # Sat: PST, 9 + 8
        ("Raffle opens Mar 8 9am PT", utc(2026, 3, 1, 15, 0), utc(2026, 3, 8, 16, 0)),    # Sun: PDT, 9 + 7
        ("Raffle opens Feb 28 9am PT", utc(2026, 2, 20, 15, 0), utc(2026, 2, 28, 17, 0)), # February is never daylight
        ("Raffle opens Apr 3 9am PT", utc(2026, 3, 20, 15, 0), utc(2026, 4, 3, 16, 0)),   # April always is
        # Daylight time ends the first Sunday of November: 2026-11-01, but 2027-11-07 (Nov 1 is a Monday).
        ("Raffle opens Oct 31 9am PT", utc(2026, 10, 25, 15, 0), utc(2026, 10, 31, 16, 0)),  # Sat: PDT
        ("Raffle opens Nov 1 9am PT", utc(2026, 10, 25, 15, 0), utc(2026, 11, 1, 17, 0)),    # Sun: PST
        ("Raffle opens Nov 6 9am PT", utc(2027, 10, 30, 15, 0), utc(2027, 11, 6, 16, 0)),    # Sat: still PDT
        ("Raffle opens Nov 7 9am PT", utc(2027, 10, 30, 15, 0), utc(2027, 11, 7, 17, 0)),    # Sun: PST
        # Daylight time starts 2027-03-14 (Mar 1 is a Monday), so Mar 13 is still standard time.
        ("Raffle opens Mar 13 9am PT", utc(2027, 3, 5, 15, 0), utc(2027, 3, 13, 17, 0)),
        ("Raffle opens Mar 14 9am PT", utc(2027, 3, 5, 15, 0), utc(2027, 3, 14, 16, 0)),
    ],
)
def test_open_dates_zones_years_and_daylight_saving(text, posted, expected_opens):
    window = raffles.entry_window(text, "", posted)

    assert window is not None
    assert window[0] == expected_opens


@pytest.mark.parametrize(
    "text, expected_opens",
    [
        ("Raffle opens 10/12/00 9am UTC", utc(2000, 10, 12, 9, 0)),     # two-digit 00 is 2000
        ("Raffle opens 10/12/2000 9am UTC", utc(2000, 10, 12, 9, 0)),   # a four-digit year is never shifted
        ("Raffle opens 10/12/1999 9am UTC", utc(1999, 10, 12, 9, 0)),
        # Posted 2026-10-09; 183 days earlier is 2026-04-09. A date that far back is still this year,
        # one day further back is read as next year.
        ("Raffle opens Apr 9 9am PT", utc(2026, 4, 9, 16, 0)),
        ("Raffle opens Apr 8 9am PT", utc(2027, 4, 8, 16, 0)),
    ],
)
def test_year_inference_boundaries(text, expected_opens):
    window = raffles.entry_window(text, "", POSTED)

    assert window == (expected_opens, None)


@pytest.mark.parametrize(
    "text, expected_opens",
    [
        # Posted 2026-10-10 02:00 UTC = Oct 9 22:00 EDT, so "today" is Oct 9 and "tomorrow" is Oct 10 in the post's zone.
        ("Raffle opens today at 9pm ET", utc(2026, 10, 10, 1, 0)),       # Oct 9 21:00 EDT = Oct 10 01:00 UTC
        ("Raffle opens tomorrow at 9pm ET", utc(2026, 10, 11, 1, 0)),    # Oct 10 21:00 EDT = Oct 11 01:00 UTC
    ],
)
def test_today_and_tomorrow_are_dates_in_the_zone_of_the_post_not_in_utc(text, expected_opens):
    posted = utc(2026, 10, 10, 2, 0)

    assert raffles.entry_window(text, "", posted)[0] == expected_opens


def test_a_cue_word_at_the_very_start_of_the_post_still_marks_a_close():
    window = raffles.entry_window("until Oct 14 9am PT", "", POSTED)

    assert window == (POSTED, utc(2026, 10, 14, 16, 0))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Raffle opens Oct 12 9am PT, or Oct 13 9am PT", (utc(2026, 10, 12, 16, 0), None)),   # first open wins
        ("Raffle until Oct 14 9am PT, until Oct 16 9am PT", (POSTED, utc(2026, 10, 14, 16, 0))),  # first close wins
    ],
)
def test_the_first_open_and_the_first_close_win(text, expected):
    assert raffles.entry_window(text, "", POSTED) == expected


def test_an_impossible_date_is_skipped_and_the_next_mention_is_used():
    window = raffles.entry_window("Raffle opens Feb 30 9am PT or Oct 12 9am PT", "", POSTED)

    assert window == (utc(2026, 10, 12, 16, 0), None)


def test_a_close_equal_to_the_open_is_a_window_and_one_minute_earlier_is_not():
    same = raffles.entry_window("Raffle opens Oct 12 9am PT until Oct 12 9am PT", "", POSTED)
    earlier = raffles.entry_window("Raffle opens Oct 12 9am PT until Oct 12 8:59am PT", "", POSTED)

    assert same == (utc(2026, 10, 12, 16, 0), utc(2026, 10, 12, 16, 0))
    assert earlier is None


def test_a_close_with_no_time_ends_at_23_59_59_in_its_zone():
    window = raffles.entry_window("Raffle opens Oct 12 9am PT, until Oct 14", "", POSTED)

    # 23:59:59 PDT = 06:59:59 UTC the next day.
    assert window == (utc(2026, 10, 12, 16, 0), utc(2026, 10, 15, 6, 59, 59))


@pytest.mark.parametrize(
    "instant, wall_clock, label",
    [
        (utc(2027, 1, 16, 14, 0), datetime(2027, 1, 16, 6, 0), "PST"),     # winter, UTC-8
        (utc(2026, 10, 12, 16, 0), datetime(2026, 10, 12, 9, 0), "PDT"),   # summer, UTC-7
        (utc(2026, 3, 7, 23, 0), datetime(2026, 3, 7, 15, 0), "PST"),      # the day before the changeover
        (utc(2026, 3, 8, 23, 0), datetime(2026, 3, 8, 16, 0), "PDT"),      # the changeover Sunday
        (utc(2026, 10, 31, 23, 0), datetime(2026, 10, 31, 16, 0), "PDT"),  # the Saturday before it ends
        (utc(2026, 11, 1, 23, 0), datetime(2026, 11, 1, 15, 0), "PST"),    # the day daylight time ends
        (utc(2027, 1, 16, 3, 0), datetime(2027, 1, 15, 19, 0), "PST"),     # local date is the day before the UTC date
    ],
)
def test_pacific_gives_the_wall_clock_and_the_zone_label(instant, wall_clock, label):
    assert raffles.pacific(instant) == (wall_clock, label)


def test_pacific_accepts_an_instant_in_another_zone():
    eastern = datetime(2026, 10, 12, 12, 0, tzinfo=timezone(timedelta(hours=-4)))

    assert raffles.pacific(eastern) == (datetime(2026, 10, 12, 9, 0), "PDT")


def test_result_datetimes_are_timezone_aware():
    opens, closes = raffles.entry_window("Entries Oct 12 9am - Oct 14 11pm PT", "", POSTED)

    assert opens.utcoffset() is not None
    assert closes.utcoffset() is not None
