"""Raffle classifier (journey 3): is a Reddit deal post a retailer raffle or invite event, and when?

Retailers (Walmart, Pokemon Center, Costco ...) sometimes sell a drop by raffle or invite instead of
first-come stock. The deal subreddits announce them. This module is pure: it reads post text and
returns an answer, with no network and no clock (the post time is passed in).

  is_raffle(title, body)                  -> bool
  entry_window(title, body, posted_at)    -> (opens, closes) | None

entry_window rules:
  * opens is the first date mentioned without a closing cue ("until", "through", "ends", "closes",
    "deadline", "by", "before", or a range dash / "to"); with no such mention it is posted_at.
  * closes is the first date with a closing cue, or None when the post names no end. A date with no
    time closes at 23:59:59 and opens at 00:00 in its zone.
  * A zone is read from the text (PT, ET, PST, EDT, UTC ...). A mention with none takes the first zone
    named anywhere in the post, else DEFAULT_ZONE. Results are timezone-aware, in UTC.
  * No usable date, or a close before the open, returns None.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

# Without a zone in the post we assume Eastern: Walmart, Target, Best Buy and GameStop all announce
# drops on the east-coast clock. An assumption, not a measurement.
DEFAULT_ZONE = "ET"

# A date more than half a year before the post is read as next year ("Jan 2" in a December post).
ROLLOVER_DAYS = 183

# Standard-time UTC offsets in hours. The generic names (PT, MT, CT, ET) follow US daylight saving;
# the explicit S/D names never move. UTC and GMT are zero. Source: US time-zone definitions.
STANDARD_OFFSET_H = {"PT": -8, "MT": -7, "CT": -6, "ET": -5}
FIXED_OFFSET_H = {
    "PST": -8, "PDT": -7, "MST": -7, "MDT": -6, "CST": -6, "CDT": -5, "EST": -5, "EDT": -4,  # magic-ok: US zone UTC offsets, named by their key
    "UTC": 0, "GMT": 0,
}

# US daylight time (2007 rule): second Sunday of March through the first Sunday of November.
DST_START_MONTH = 3
DST_START_SUNDAY = 2
DST_END_MONTH = 11
DST_END_SUNDAY = 1
SUNDAY = 6  # date.weekday()
DAYS_PER_WEEK = 7  # nomutate: SUNDAY - weekday is 0..6, so any modulus above 6 gives the same result

END_OF_DAY = (23, 59, 59)
NOON_HOUR = 12
TWO_DIGIT_YEAR_BASE = 2000

# Retailers that run raffles and invites; matched as lowercase substrings of the post text.
RETAILERS = (
    "walmart", "target", "best buy", "bestbuy", "gamestop", "costco", "sam's club", "sams club",
    "amazon", "pokemon center", "pokemoncenter", "walgreens", "barnes",
)
# A weak raffle word only counts in a post about trading cards.
CARD_WORDS = (
    "pokemon", "pokémon", "tcg", "trading card", "one piece", "lorcana", "magic: the gathering",
    "etb", "booster", "elite trainer",
)
STRONG_RE = re.compile(r"\braffles?\b|\blottery\b|request an invite|invite[- ]only|invitation[- ]only")
WEAK_RE = re.compile(
    r"\bsign[- ]?up\b|\bentry\b|\bentries\b|\benter\b|\binvites?\b|\binvitations?\b|\bdrawing\b"
)
# A user's own giveaway, not a retailer event.
USER_RUN_RE = re.compile(
    r"giveaways?\b|giving away|\bmy (?:own )?raffle|\bour raffle|i'?m hosting|i am hosting|\bhosting a raffle"
)
RESTOCK_RE = re.compile(r"in stock|restock|add to cart|back in stock|sold out")

MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
ZONE_NAMES = "PST|PDT|PT|MST|MDT|MT|CST|CDT|CT|EST|EDT|ET|UTC|GMT"

MENTION_RE = re.compile(
    r"\b(?:(?P<rel>today|tomorrow)"
    r"|(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\b"
    r"|(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?\b)"
    r"(?:\s*(?:at|@|,)?\s*(?P<h>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ap>am|pm)\b"
    rf"(?:\s*(?P<tz>{ZONE_NAMES})\b)?)?",
    re.IGNORECASE,
)
CLOSE_CUE_RE = re.compile(
    r"(?:\b(?:until|through|thru|till|ends?|closes?|closing|deadline|by|before|to)\b|[-–—])"
    r"\s*(?:on|at|@)?\s*$"
)
CUE_LOOKBEHIND = 20  # characters before a date that can hold its cue word


# -- is_raffle ---------------------------------------------------------------------------

def is_raffle(title: str, body: str) -> bool:
    """True for a retailer raffle / invite event post; False for user giveaways and restocks."""
    text = f"{title}\n{body}".lower()
    if USER_RUN_RE.search(text):
        return False
    if STRONG_RE.search(text):
        return True
    if not WEAK_RE.search(text) or RESTOCK_RE.search(text):
        return False
    return any(r in text for r in RETAILERS) and any(w in text for w in CARD_WORDS)


# -- time zones --------------------------------------------------------------------------

def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(SUNDAY - first.weekday()) % DAYS_PER_WEEK)
    return first_sunday + timedelta(weeks=n - 1)


def _is_dst(day: date) -> bool:
    start = _nth_sunday(day.year, DST_START_MONTH, DST_START_SUNDAY)
    end = _nth_sunday(day.year, DST_END_MONTH, DST_END_SUNDAY)
    return start <= day < end


def _offset(zone: str, day: date) -> timedelta:
    zone = zone.upper()
    if zone in FIXED_OFFSET_H:
        return timedelta(hours=FIXED_OFFSET_H[zone])
    hours = STANDARD_OFFSET_H[zone] + (1 if _is_dst(day) else 0)
    return timedelta(hours=hours)


PACIFIC_ZONE = "PT"
PACIFIC_STANDARD_LABEL = "PST"
PACIFIC_DAYLIGHT_LABEL = "PDT"


def pacific(instant: datetime) -> tuple[datetime, str]:
    """(naive wall-clock datetime, 'PST' or 'PDT') for an aware instant in US Pacific time.

    Daylight time is decided by the UTC date, the same day-level rule the parser uses, so a time within
    hours of the 2 a.m. changeover can be an hour off.
    """
    utc = instant.astimezone(UTC)
    day = utc.date()
    local = (utc + _offset(PACIFIC_ZONE, day)).replace(tzinfo=None)
    return local, PACIFIC_DAYLIGHT_LABEL if _is_dst(day) else PACIFIC_STANDARD_LABEL


def _as_utc(posted_at: datetime | float | int) -> datetime:
    # Duck-typed: the test clock swaps this module's datetime class, so isinstance would miss a real one.
    if hasattr(posted_at, "tzinfo"):
        return posted_at.replace(tzinfo=UTC) if posted_at.tzinfo is None else posted_at.astimezone(UTC)
    return datetime.fromtimestamp(posted_at, UTC)


# -- entry_window ------------------------------------------------------------------------

def _mention_date(m: re.Match, posted_local: datetime) -> date | None:
    """The calendar date a mention names, or None when it is not a real date."""
    today = posted_local.date()
    if m["rel"]:
        return today + timedelta(days=1 if m["rel"].lower() == "tomorrow" else 0)
    if m["mon"]:
        month, day, year = MONTHS[m["mon"].lower()], int(m["day"]), None
    else:
        month, day, year = int(m["m"]), int(m["d"]), m["y"]
    try:
        if year:
            y = int(year)
            return date(y + TWO_DIGIT_YEAR_BASE if len(year) == 2 else y, month, day)
        found = date(today.year, month, day)
        if found < today - timedelta(days=ROLLOVER_DAYS):
            found = date(today.year + 1, month, day)
        return found
    except ValueError:
        return None


def _mention_time(m: re.Match, is_close: bool) -> tuple[int, int, int]:
    if not m["h"]:
        return END_OF_DAY if is_close else (0, 0, 0)
    hour = int(m["h"]) % NOON_HOUR + (NOON_HOUR if m["ap"].lower() == "pm" else 0)
    return hour, int(m["min"] or 0), 0


def _mention_instant(m: re.Match, zone: str, posted: datetime, is_close: bool) -> datetime | None:
    posted_local = posted + _offset(zone, posted.date())
    day = _mention_date(m, posted_local)
    if day is None:
        return None
    hour, minute, second = _mention_time(m, is_close)
    local = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)
    return local - _offset(zone, day)


def entry_window(title: str, body: str, posted_at: datetime | float | int):
    """(opens, closes) as aware UTC datetimes, closes None if unstated; None if no usable date."""
    text = f"{title}\n{body}"
    posted = _as_utc(posted_at)
    mentions = list(MENTION_RE.finditer(text))
    zone = next((m["tz"].upper() for m in mentions if m["tz"]), DEFAULT_ZONE)
    opens = closes = None
    for m in mentions:
        before = text[max(0, m.start() - CUE_LOOKBEHIND):m.start()].lower()
        is_close = bool(CLOSE_CUE_RE.search(before))
        if (is_close and closes is not None) or (not is_close and opens is not None):
            continue
        instant = _mention_instant(m, (m["tz"] or zone).upper(), posted, is_close)
        if instant is None:
            continue
        if is_close:
            closes = instant
        else:
            opens = instant
    if opens is None and closes is None:
        return None
    opens = opens or posted
    if closes is not None and closes < opens:
        return None
    return opens, closes
