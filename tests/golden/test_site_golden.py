"""Status page golden: the built index.html does not change unless the page is meant to change.

Oracle: the page is a pure function of config + poll state + price history + the (frozen) clock, so a
fixed set of those must build the same bytes every time. The snapshot in fixtures/site_index.html was
captured from the single-file site.py before it was split into templates; a refactor passes only if
the output stays identical. When the page is meant to change, rebuild the snapshot and read the diff
as the review (never edit it to make a test pass).

Line endings are normalized on both sides: site.py writes text mode, so the file has CRLF on Windows
and LF elsewhere, and git may convert the snapshot on checkout.
"""

import datetime as real_datetime
import json
import shutil
from pathlib import Path

from tcgwatch import site as site_mod
from tcgwatch.config import Feed, Product
from tests.builders import make_config

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "site_index.html"


class _UtcDatetime(real_datetime.datetime):
    """datetime.now() on the frozen instant, read as UTC so the golden does not depend on the machine's zone."""

    _clock = None

    @classmethod
    def now(cls, tz=None):
        return real_datetime.datetime.fromtimestamp(cls._clock.now, real_datetime.timezone.utc).replace(tzinfo=None)


def build_page(tmp_path, monkeypatch, clock) -> bytes:
    """Build the page from tests/golden/fixtures/* and return its bytes with LF line endings."""
    raw = json.loads((FIXTURES / "config.json").read_text(encoding="utf-8"))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(FIXTURES / "state.json", data_dir / "state.json")
    shutil.copy(FIXTURES / "price_history.jsonl", data_dir / "price_history.jsonl")
    cfg = make_config(
        data_dir,
        products=[Product(p["retailer"], p["id"], p["name"], msrp=p["msrp"]) for p in raw["products"]],
        feeds=[Feed(f["subreddit"], f["keywords"]) for f in raw["feeds"]],
        releases=raw["releases"],
        discord_invite=raw["discord_invite"],
    )
    _UtcDatetime._clock = clock
    monkeypatch.setattr(site_mod, "datetime", _UtcDatetime)
    monkeypatch.setattr(site_mod.ev, "match_group", lambda name: None)  # would read pull rates, may price singles
    monkeypatch.setattr(site_mod.images, "export_mascot", lambda src, out: True)  # PIL work; the page embeds only True
    out = site_mod.build(cfg, tmp_path / "site")
    return out.read_bytes().replace(b"\r\n", b"\n")


def test_page_built_from_the_fixture_state_matches_the_golden_snapshot(tmp_path, monkeypatch, clock):
    built = build_page(tmp_path, monkeypatch, clock)

    golden = GOLDEN.read_bytes().replace(b"\r\n", b"\n")
    assert built == golden, "page output changed; if intended, rebuild fixtures/site_index.html and review the diff"
