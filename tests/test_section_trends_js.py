"""The browser half of the trends section (templates/sections/trends.js), run under node.

Oracle: docs/trends.md "Deal bands" and the Trends card rules. The provider bakes the ceilings, so the
browser only compares the typed price against deal_below first, then fair_below, and a price under
both is a deal. The worked example is MSRP 49.99 and market 80: deal_below 54.989, fair_below 72.0;
54.98 is deal, 54.99 is fair, 72.00 is fair, 72.01 is high. A ceiling prints rounded down to the
cent, so the deal line reads $54.98. A game card prints how far its index is under the window high.

The script runs exactly as shipped: its source, with the copy placeholders filled the way the page
build fills them, is evaluated in node with an empty page (no `D.trends`, so its setup returns at
once) and a few page helpers stubbed. node runs a local file only; the no-network fixture blocks
subprocesses, so this module puts the real process starter back for these tests alone. Without node
the tests skip, and test_section_trends.py::test_the_section_script_holds_no_threshold_arithmetic
still guards the script.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tcgwatch import site as site_mod
from tcgwatch import trends as rules
from tcgwatch.site_data import trends as provider
from tests.builders import make_config

# Taken at import, before conftest's no_network fixture replaces it for each test.
REAL_POPEN_INIT = subprocess.Popen.__init__
NODE = shutil.which("node")
KEY = "Pokemon|prismatic evolutions elite trainer box"

# argv: the filled script, then {"fn", "args", "price"}. The stubs stand in for page.js helpers.
RUN_JS = """
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const call = JSON.parse(process.argv[2]);
const env = {D: {trends: null}, gameTag: g => '[' + g + ']', gameGlyph: g => '<' + g + '>',
  money: v => '$' + v.toFixed(2), $: () => ({value: call.price}), live: () => []};
const fns = new Function(...Object.keys(env), src + '\\nreturn {trBand, trGameCard, trVerdict, trSparkRange, trSpark, trFilter, trStep, trEnterPick, trPlace};')(...Object.values(env));
process.stdout.write(JSON.stringify(fns[call.fn](...call.args)));
"""

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


@pytest.fixture
def run_js(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess.Popen, "__init__", REAL_POPEN_INIT)
    script = tmp_path / "trends.js"
    script.write_text(site_mod._fill((site_mod.SECTIONS / "trends.js").read_text(encoding="utf-8"),
                                     site_mod.copy_context()), encoding="utf-8")

    def run(fn, args, price=""):
        done = subprocess.run([NODE, "-e", RUN_JS, str(script), json.dumps({"fn": fn, "args": args, "price": price})],
                              capture_output=True, text=True, timeout=30, check=True)
        return json.loads(done.stdout)

    return run


def bands_of(tmp_path, msrp, market) -> dict:
    group = {"key": KEY, "game": "Pokemon", "name": "Prismatic Evolutions Elite Trainer Box",
             "msrp": msrp, "market": {"price": market} if market is not None else None, "listings": []}
    return provider.provide(make_config(tmp_path), None, [group])["trends"]["products"][KEY]


# -- the verdict ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "price, expected",
    [(54.98, "deal"), (54.99, "fair"), (72.00, "fair"), (72.01, "high"), (40.00, "deal")],
)
def test_the_docs_worked_example_gets_the_documented_verdicts(run_js, tmp_path, price, expected):
    bands = bands_of(tmp_path, msrp=49.99, market=80.0)

    assert run_js("trBand", [price, bands]) == expected


@pytest.mark.parametrize(
    "bands, price, expected",
    [
        ({"deal_below": 110.0, "fair_below": 180.0}, 100.0, "deal"),   # under both: deal wins
        ({"deal_below": 110.0, "fair_below": 45.0}, 44.0, "deal"),     # under both, fair below deal: deal wins
        ({"deal_below": 110.0, "fair_below": 110.0}, 110.0, "deal"),   # on both: deal wins
        ({"deal_below": 110.0, "fair_below": 180.0}, 150.0, "fair"),
        ({"deal_below": None, "fair_below": 72.0}, 50.0, "fair"),      # no MSRP: only the fair ceiling
        ({"deal_below": 54.989, "fair_below": None}, 60.0, "high"),    # no market: only the deal ceiling
        ({"deal_below": None, "fair_below": None}, 1.0, "high"),
    ],
)
def test_deal_is_checked_before_fair_and_a_missing_ceiling_is_skipped(run_js, bands, price, expected):
    assert run_js("trBand", [price, bands]) == expected


@pytest.mark.parametrize(
    "msrp, market, price, shown",
    [
        (49.99, 80.0, "54.98", "At or under $54.98, close to MSRP."),    # 54.989 prints rounded down
        (49.99, 80.0, "54.99", "Under $72.00, below what it sells for online."),
        (49.99, 80.0, "72.01", "Over the fair price of $72.00."),
        (49.99, 50.0, "60", "Over the deal price of $54.98."),            # fair 45.00 is under deal: the larger one
    ],
)
def test_the_verdict_explains_itself_with_the_provider_baked_ceilings(run_js, tmp_path, msrp, market, price, shown):
    verdict = run_js("trVerdict", [bands_of(tmp_path, msrp, market)], price=price)

    assert shown in verdict


# -- the game card -------------------------------------------------------------------------------

def card(below_high, latest=98.5, at_peak=True):
    return ["Pokemon", {"status": "ok", "early": False, "index": [["2026-09-06", 100.0], ["2026-12-01", latest]],
                        "latest": latest, "at_peak": at_peak, "below_high": below_high}]


def test_a_card_at_its_peak_says_how_far_under_the_high_it_is(run_js):
    html = run_js("trGameCard", [card(below_high=1.5)])

    assert f"At {rules.WINDOW_DAYS}-day peak" in html
    assert "-1.5%" in html
    assert f"1.5% under its {rules.WINDOW_DAYS}-day high" in html


def test_a_card_at_its_high_has_no_under_the_high_line(run_js):
    html = run_js("trGameCard", [card(below_high=0.0, latest=110.0)])

    assert "under its" not in html


def test_a_card_far_under_its_high_says_so_too(run_js):
    html = run_js("trGameCard", [card(below_high=20.0, latest=120.0, at_peak=False)])

    assert f"20% under its {rules.WINDOW_DAYS}-day high" in html


# -- the sparkline (David, 2026-10-09: "the graph seems pretty flat") -----------------------------
# The y-range fits the plotted values, never 0 or a fixed scale, so a small move fills the box. A
# floor on the span keeps day-to-day noise from looking like a crash; padding keeps the stroke inside.

@pytest.mark.parametrize(
    "vals, min_span, pad, expected",
    [
        # span 110 - 100 = 10, over the floor 4; pad 10% of 10 = 1 each side.
        ([100.0, 110.0, 105.0], 4, 0.1, [99.0, 111.0]),
        # The docs/trends.md worked example, 100 -> 137.5: span 37.5, pad 3.75. Not anchored at 0.
        ([100.0, 110.0, 137.5], 4, 0.1, [96.25, 141.25]),
        # span 1 is under the floor 4: centred on 100.5, 98.5..102.5, then pad 0.4 -> 98.1..102.9.
        ([100.0, 101.0], 4, 0.1, [98.1, 102.9]),
    ],
)
def test_the_sparkline_y_range_fits_the_plotted_values(run_js, vals, min_span, pad, expected):
    assert run_js("trSparkRange", [vals, min_span, pad]) == pytest.approx(expected)


def spark_points(svg):
    pts = re.search(r'points="([^"]+)"', svg).group(1).split()
    return [tuple(float(n) for n in p.split(",")) for p in pts]


SPARK_INDEX = [["2026-09-01", 100.0], ["2026-09-15", 110.0], ["2026-09-29", 137.5]]  # docs/trends.md


def test_the_sparkline_draws_the_base_date_line_through_its_first_point(run_js):
    svg = run_js("trSpark", [SPARK_INDEX])

    base_y = float(re.search(r'class="tr-base"[^>]*y1="([\d.]+)"', svg).group(1))

    assert spark_points(svg)[0][1] == pytest.approx(base_y)


def test_the_sparkline_spaces_points_by_date_not_by_count(run_js):
    # 09-15 is 14 of 28 days in, so it sits halfway along; a gap in the history shows as a gap.
    index = [["2026-09-01", 100.0], ["2026-09-15", 110.0], ["2026-09-29", 137.5]]
    uneven = [["2026-09-01", 100.0], ["2026-09-08", 110.0], ["2026-09-29", 137.5]]

    (x0, _), (x1, _), (x2, _) = spark_points(run_js("trSpark", [index]))
    (_, _), (u1, _), (_, _) = spark_points(run_js("trSpark", [uneven]))

    assert x1 == pytest.approx((x0 + x2) / 2)
    assert u1 == pytest.approx(x0 + (x2 - x0) / 4)  # 7 of 28 days


def test_the_sparkline_puts_the_window_high_at_the_top_and_the_low_at_the_bottom(run_js):
    ys = [y for _, y in spark_points(run_js("trSpark", [SPARK_INDEX]))]

    # svg y grows downward: the high (137.5, last) is the smallest y, the low (100, first) the largest.
    assert ys.index(min(ys)) == 2
    assert ys.index(max(ys)) == 0


# -- the product picker (David, 2026-10-09: pictures in the dropdown) -----------------------------

PICKER = [{"key": "a", "game": "Pokemon", "name": "Prismatic Evolutions Elite Trainer Box"},
          {"key": "b", "game": "Pokemon", "name": "Prismatic Evolutions Booster Bundle"},
          {"key": "c", "game": "One Piece", "name": "OP-09 Booster Box"},
          {"key": "d", "game": "Riftbound", "name": "Origins Booster Display"}]


@pytest.mark.parametrize(
    "q, keys",
    [
        ("prism box", ["a"]),               # every word must appear, in any order
        ("BOOSTER", ["b", "c", "d"]),       # case ignored
        ("riftbound", ["d"]),               # the game counts, though the shown name drops it (QA 2026-10-09)
        ("elite pokemon", ["a"]),           # game and name words in any order
        ("one piece box", ["c"]),
        ("", ["a", "b", "c", "d"]),         # nothing typed: browse every product
        ("  ", ["a", "b", "c", "d"]),
        ("zzz", []),
    ],
)
def test_the_picker_keeps_products_whose_name_has_every_typed_word(run_js, q, keys):
    assert [g["key"] for g in run_js("trFilter", [PICKER, q])] == keys


@pytest.mark.parametrize(
    "active, key, expected",
    [
        (-1, "ArrowDown", 0), (0, "ArrowDown", 1), (2, "ArrowDown", 0),   # wraps past the last
        (-1, "ArrowUp", 2), (0, "ArrowUp", 2), (2, "ArrowUp", 1),         # wraps past the first
        (1, "Home", 1), (1, "a", 1),                                    # Home stays with the caret
    ],
)
def test_arrow_keys_move_the_active_option_and_wrap(run_js, active, key, expected):
    assert run_js("trStep", [active, 3, key]) == expected


@pytest.mark.parametrize(
    "active, n, expected",
    [
        (2, 5, 2),     # the highlighted option
        (-1, 5, 0),    # nothing highlighted: the first match (QA 2026-10-09: "30th celebration elite" + Enter did nothing)
        (-1, 0, -1),   # no matches: nothing to pick
    ],
)
def test_enter_picks_the_highlighted_option_or_else_the_first_match(run_js, active, n, expected):
    assert run_js("trEnterPick", [active, n]) == expected


# The list opens toward the room it needs, preferring up so the field stays low in the thumb zone, and
# is never taller than the room on its side (QA 2026-10-09: 296px list, 258px above, top option cut off).
@pytest.mark.parametrize(
    "above, below, want, expected",
    [
        (400, 100, 296, {"up": True, "max": 296}),     # fits above: up, as tall as it wants
        (258, 500, 296, {"up": False, "max": 296}),    # does not fit above but fits below: down
        (258, 120, 296, {"up": True, "max": 258}),     # fits neither: the larger side, clamped to its room
        (90, 200, 296, {"up": False, "max": 200}),
        (300, 300, 120, {"up": True, "max": 120}),     # a short list: up, its own height
    ],
)
def test_the_list_opens_toward_the_room_it_needs_and_never_past_it(run_js, above, below, want, expected):
    assert run_js("trPlace", [above, below, want]) == expected
