"""The "Is it a deal?" section (journey 5): templates/sections/trends.html|css|js.

Oracle: templates/page.html (where `{{sections_html}}` sits: after the local shops, before the filter
bar), site.render (a section's css follows page.css, its js follows page.js), the Architecture rules in
the shared agent instructions (copy lives in copy.json, colours are page.css tokens, no hand-mirrored
logic) and docs/trends.md. The verdict itself is run under node in test_section_trends_js.py against
the docs/trends.md example (54.98 deal, 54.99 fair, 72.01 high); here the script is checked for any
threshold arithmetic of its own.
"""

import json
import re

import pytest

from tcgwatch import site as site_mod
from tcgwatch import trends as rules

SECTION = site_mod.SECTIONS
PARTS = ("html", "css", "js")
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")
SECTION_PREFIX = "tr_"  # the section's own copy keys


def words(key):
    return json.loads((site_mod.TEMPLATES / "copy.json").read_text(encoding="utf-8"))[key]


def source(kind):
    return (SECTION / f"trends.{kind}").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page():
    return site_mod.render({})


def test_the_section_sits_above_the_product_list_and_its_filter_bar(page):
    # David, 2026-10-09: most products sit above MSRP, so the deal check leads the page.
    assert page.index('</header>') < page.index('id="trWrap"') < page.index('id="reelWrap"') < page.index('<div class="bar">')


def test_the_section_starts_hidden_so_a_page_without_trends_data_shows_nothing(page):
    assert '<section class="tr-wrap" id="trWrap" hidden>' in page


def test_the_heading_comes_from_copy_json(page):
    assert f'<span class="micro">{words("tr_heading")}</span>' in page


def test_the_section_style_is_in_the_page_stylesheet(page):
    assert page.index("<style>") < page.index(source("css").strip()) < page.index("</style>")


def test_the_section_script_runs_after_the_page_script(page):
    assert page.index("stats(); apply(); fromHash();") < page.index("(function trSetup(){") < page.index("</script>\n</body>")


@pytest.mark.parametrize("kind", PARTS)
def test_every_placeholder_in_the_section_has_a_copy_key(kind):
    copy = json.loads((site_mod.TEMPLATES / "copy.json").read_text(encoding="utf-8"))

    missing = sorted(set(PLACEHOLDER.findall(source(kind))) - copy.keys())

    assert missing == []


def test_every_section_copy_key_is_used_by_the_section():
    copy = json.loads((site_mod.TEMPLATES / "copy.json").read_text(encoding="utf-8"))
    used = {k for kind in PARTS for k in PLACEHOLDER.findall(source(kind))}

    unused = sorted(k for k in copy if k.startswith(SECTION_PREFIX) and k not in used)

    assert unused == []


LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
# Maths on a ceiling, rounding, or one ceiling compared with the other: the provider owns all of it.
THRESHOLD_ARITHMETIC = [
    re.compile(r"Math\.(?:floor|ceil|round|trunc)"),
    re.compile(r"\b(?:deal|fair)_below\s*[-+*/]"),
    re.compile(r"[-+*/]\s*(?:b\.)?(?:deal|fair)_below"),
    re.compile(r"\b(?:deal|fair)_below\s*[<>]=?\s*b\.(?:deal|fair)_below"),
    re.compile(r"TR_CENT"),
]


@pytest.mark.parametrize("pattern", THRESHOLD_ARITHMETIC, ids=lambda p: p.pattern)
def test_the_section_script_holds_no_threshold_arithmetic(pattern):
    code = LINE_COMMENT.sub("", source("js"))

    assert pattern.search(code) is None


@pytest.mark.parametrize("key", ["tr_at_peak", "tr_peak_warn", "tr_under_high"])
def test_the_peak_window_in_the_copy_is_filled_from_the_trends_window(monkeypatch, key):
    template = words(key)
    monkeypatch.setattr(rules, "WINDOW_DAYS", 60)

    page = site_mod.render({})

    assert "{{window_days}}" in template
    assert template.replace("{{window_days}}", "60") in page


def test_no_trends_copy_hard_codes_the_window_length():
    copy = json.loads((site_mod.TEMPLATES / "copy.json").read_text(encoding="utf-8"))

    hard_coded = sorted(k for k, v in copy.items() if k.startswith(SECTION_PREFIX) and str(rules.WINDOW_DAYS) in v)

    assert hard_coded == []


def test_the_stylesheet_uses_only_page_css_tokens_for_colour():
    assert COLOUR_LITERAL.findall(source("css")) == []


def test_the_price_input_opens_the_decimal_keypad_on_a_phone():
    assert 'id="trPrice" type="text" inputmode="decimal"' in source("html")


def test_the_inputs_come_after_the_verdict_so_they_sit_in_the_thumb_zone():
    html = source("html")

    assert html.index('id="trOut"') < html.index('class="tr-inputs"')
