"""Status page extension points: a section file or a data provider is added without editing site.py.

Covers tcgwatch/site_data/__init__.py (the provider loader) and the section assembly in site.py.

Oracle (site.py docstring): a section is templates/sections/<name>.html|css|js; its html follows the
local-shops section, its css ends the stylesheet, its js ends the script. A provider is
site_data/<name>.py with provide(cfg, state, groups) -> dict, merged into the page data; a key the page
already uses fails the build. Every test builds in a tmp_path folder, so the real templates/sections
and site_data folders are never written.
"""

import json

import pytest

from tcgwatch import site as site_mod, site_data
from tcgwatch.config import Product
from tests.builders import make_config

BAR_START = '\n\n<div class="bar">'


@pytest.fixture
def sections(tmp_path, monkeypatch):
    folder = tmp_path / "sections"
    folder.mkdir()
    monkeypatch.setattr(site_mod, "SECTIONS", folder)
    return folder


@pytest.fixture
def providers(tmp_path, monkeypatch):
    folder = tmp_path / "providers"
    folder.mkdir()
    monkeypatch.setattr(site_data, "PROVIDER_DIR", folder)
    return folder


def collect_with_one_product(tmp_path):
    cfg = make_config(tmp_path, products=[Product("target", "111", "Pokemon Prismatic Evolutions Elite Trainer Box", msrp=49.99)])
    return site_mod.collect(cfg)


def test_a_section_html_file_sits_between_the_local_shops_and_the_filter_bar(sections):
    (sections / "journeys.html").write_text('<section id="journeys">J</section>\n', encoding="utf-8")

    page = site_mod.render({})

    assert '</section>\n<section id="journeys">J</section>' + BAR_START in page


def test_a_section_marked_place_top_sits_between_the_header_and_the_hot_reel(sections):
    (sections / "journeys.html").write_text('<!-- place: top -->\n<section id="journeys">J</section>\n', encoding="utf-8")

    page = site_mod.render({})

    assert '</header>\n<section id="journeys">J</section>\n\n<section class="reel-wrap"' in page


def test_a_section_marked_place_top_is_not_also_placed_after_the_local_shops(sections):
    (sections / "journeys.html").write_text('<!-- place: top -->\n<section id="journeys">J</section>\n', encoding="utf-8")

    page = site_mod.render({})

    assert page.count('id="journeys"') == 1
    assert BAR_START in page, "the filter bar still follows the local shops directly"


def test_the_place_marker_is_not_written_into_the_page(sections):
    (sections / "journeys.html").write_text('<!-- place: top -->\n<p>J</p>', encoding="utf-8")

    page = site_mod.render({})

    assert "place: top" not in page


def test_an_unknown_place_fails_the_build_and_names_it(sections):
    (sections / "journeys.html").write_text("<!-- place: sideways -->\n<p>J</p>", encoding="utf-8")

    with pytest.raises(ValueError, match="journeys.html.*sideways"):
        site_mod.render({})


def test_the_trends_section_is_placed_at_the_top_of_the_real_page():
    page = site_mod.render({})

    assert page.index('id="trWrap"') < page.index('id="reelWrap"')


def test_a_section_css_file_is_the_last_thing_in_the_stylesheet(sections):
    (sections / "journeys.css").write_text("#journeys { color:red; }", encoding="utf-8")

    page = site_mod.render({})

    assert "#journeys { color:red; }\n</style>" in page


def test_a_section_js_file_runs_after_the_page_script(sections):
    (sections / "journeys.js").write_text("window.journeysLoaded = true;", encoding="utf-8")

    page = site_mod.render({})

    assert "stats(); apply(); fromHash();\nwindow.journeysLoaded = true;\n</script>" in page


def test_a_section_with_only_a_stylesheet_adds_no_html_and_no_script(sections):
    bare = site_mod.render({})
    (sections / "plain.css").write_text("#plain { top:0; }", encoding="utf-8")

    with_css = site_mod.render({})

    assert with_css == bare.replace("</style>", "#plain { top:0; }\n</style>")


def test_sections_are_added_in_name_order(sections):
    (sections / "b_second.html").write_text("<p>second</p>", encoding="utf-8")
    (sections / "a_first.html").write_text("<p>first</p>", encoding="utf-8")

    page = site_mod.render({})

    assert page.index("<p>first</p>") < page.index("<p>second</p>")


def test_a_section_can_use_a_copy_key(sections):
    (sections / "journeys.html").write_text("<h2>{{hot_heading}}</h2>", encoding="utf-8")
    heading = json.loads((site_mod.TEMPLATES / "copy.json").read_text(encoding="utf-8"))["hot_heading"]

    page = site_mod.render({})

    assert f"<h2>{heading}</h2>" in page


def test_a_placeholder_with_no_copy_key_fails_the_build_and_names_the_key(sections):
    (sections / "journeys.html").write_text("<h2>{{no_such_key}}</h2>", encoding="utf-8")

    with pytest.raises(KeyError, match="no_such_key"):
        site_mod.render({})


def test_a_provider_dict_is_merged_into_the_page_data(tmp_path, providers):
    (providers / "journeys.py").write_text("def provide(cfg, state, groups):\n    return {'journeys': [1, 2]}\n", encoding="utf-8")

    data = collect_with_one_product(tmp_path)

    assert data["journeys"] == [1, 2]
    assert [g["game"] for g in data["groups"]] == ["Pokemon"], "the core data is still there"


def test_a_provider_receives_the_config_the_state_and_the_finished_groups(tmp_path, providers):
    (providers / "echo.py").write_text(
        "def provide(cfg, state, groups):\n"
        "    return {'echo': {'zip': cfg.zip_code, 'names': [g['name'] for g in groups], 'state': type(state).__name__}}\n",
        encoding="utf-8",
    )

    data = collect_with_one_product(tmp_path)

    assert data["echo"] == {"zip": "00000", "names": ["Prismatic Evolutions Elite Trainer Box"], "state": "State"}


def test_a_provider_that_reuses_a_core_data_key_fails_the_build(tmp_path, providers):
    (providers / "bad.py").write_text("def provide(cfg, state, groups):\n    return {'groups': []}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="bad.py reuses page data keys: groups"):
        collect_with_one_product(tmp_path)


def test_two_providers_returning_the_same_key_fail_the_build(tmp_path, providers):
    for name in ("one.py", "two.py"):
        (providers / name).write_text("def provide(cfg, state, groups):\n    return {'shared': 1}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="two.py reuses page data keys: shared"):
        collect_with_one_product(tmp_path)


def test_a_provider_module_without_provide_fails_the_build(tmp_path, providers):
    (providers / "empty.py").write_text("X = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty.py has no provide"):
        collect_with_one_product(tmp_path)


def test_a_module_whose_name_starts_with_an_underscore_is_not_a_provider(tmp_path, providers):
    (providers / "_helper.py").write_text("raise RuntimeError('must not be imported')\n", encoding="utf-8")

    data = collect_with_one_product(tmp_path)

    assert len(data["groups"]) == 1, "collect ran without importing the underscore module"
