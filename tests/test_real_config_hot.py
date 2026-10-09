"""The real config.yaml's hot overrides (David, 2026-10-09; README "Hot items").

Oracle: Riftbound Vault Bundles and the 30th Celebration Sylveon / Greninja ex Boxes are hot
by override; every other product named below stays not hot by the name rule.
"""

from pathlib import Path

import pytest
import yaml

from tcgwatch import config, hotlist

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def products(tmp_path_factory):
    raw = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    folder = tmp_path_factory.mktemp("real_config")
    raw["data_dir"] = str(folder / "data")  # load() creates the data dir; keep it out of the home folder
    copy = folder / "config.yaml"
    copy.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return config.load(copy).products


def hot_of(products, text):
    matching = [p for p in products if text in p.name]
    assert matching, f"no product line names {text!r}"
    return {hotlist.is_hot(p.name, p.hot) for p in matching}


@pytest.mark.parametrize("text", [
    "Riftbound Vendetta Vault Bundle",
    "Riftbound Unleashed Vault Bundle",
    "30th Celebration Sylveon ex Box",
    "30th Celebration Greninja ex Box",
])
def test_the_named_products_are_hot_on_every_line(products, text):
    assert hot_of(products, text) == {True}


@pytest.mark.parametrize("text", [
    "Booster (bundle or box, verify)",
    "First Partner Illustration Collection",
    "30th Celebration Poster Collection",
    "30th Celebration Knock Out Collection",
    "30th Celebration Tech Sticker Collection",
])
def test_the_named_products_stay_not_hot_on_every_line(products, text):
    assert hot_of(products, text) == {False}
