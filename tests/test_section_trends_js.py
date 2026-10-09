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
const fns = new Function(...Object.keys(env), src + '\\nreturn {trBand, trGameCard, trVerdict};')(...Object.values(env));
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
