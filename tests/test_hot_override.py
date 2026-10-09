"""Per-product hot override: `hot: true` or `hot: false` in config.yaml beats the name rule.

Oracle (README "Hot items"): the hot rule reads the product name; a product line in config.yaml may carry
`hot: true` (track it although its name is not a hot type) or `hot: false` (skip it although it is), and
leaving `hot` out keeps the name rule. The override reaches every place the rule is used: the poll list,
the market tick and the status page. Nothing is fetched; config is read from a hand-written yaml file.
"""

from __future__ import annotations

import pytest

from tcgwatch import config as config_mod
from tcgwatch import site as site_mod
from tcgwatch import watcher as watcher_mod
from tcgwatch.config import Product
from tcgwatch.hotlist import is_hot
from tests.builders import make_config, make_watcher

TIN = "Pokemon Old Set Tin"                   # not hot by name (tins are not)
ETB = "Pokemon Prismatic Evolutions Elite Trainer Box"  # hot by name


@pytest.mark.parametrize(
    "name, override, expected",
    [
        (TIN, True, True),     # forced hot
        (ETB, False, False),   # forced not hot
        (TIN, False, False),
        (ETB, True, True),
        (TIN, None, False),    # no override: the name rule decides
        (ETB, None, True),
    ],
)
def test_the_override_beats_the_name_rule_and_none_defers_to_it(name, override, expected):
    assert is_hot(name, override) is expected


def test_is_hot_without_an_override_argument_uses_the_name_rule():
    assert is_hot(ETB) is True
    assert is_hot(TIN) is False


def write_config(tmp_path, products_yaml: str):
    path = tmp_path / "config.yaml"
    path.write_text(f"data_dir: {tmp_path.as_posix()}/data\nproducts:\n{products_yaml}", encoding="utf-8")
    return path


def test_config_reads_hot_true_false_and_absent(tmp_path):
    path = write_config(tmp_path, (
        "  - {retailer: target, id: '1', name: A, hot: true}\n"
        "  - {retailer: target, id: '2', name: B, hot: false}\n"
        "  - {retailer: target, id: '3', name: C}\n"
    ))

    cfg = config_mod.load(path)

    assert [p.hot for p in cfg.products] == [True, False, None]


def test_config_rejects_a_hot_value_that_is_not_true_or_false(tmp_path):
    path = write_config(tmp_path, "  - {retailer: target, id: '1', name: A, hot: maybe}\n")

    with pytest.raises(ValueError, match=r"hot must be true or false \(got 'maybe'\)"):
        config_mod.load(path)


def test_a_product_has_no_override_by_default():
    assert Product("target", "1", "A").hot is None


FORCED_HOT_TIN = Product("target", "3", TIN, msrp=24.99, hot=True)
FORCED_COLD_ETB = Product("target", "1", ETB, msrp=49.99, hot=False)
PLAIN_ETB = Product("target", "2", "Pokemon Booster Bundle Beta", msrp=26.94)


def test_the_watcher_polls_a_forced_hot_tin_and_skips_a_forced_cold_etb(tmp_path):
    w = make_watcher(tmp_path, products=[FORCED_COLD_ETB, FORCED_HOT_TIN, PLAIN_ETB])

    assert w.active_products("target") == [FORCED_HOT_TIN, PLAIN_ETB]


def test_the_market_tick_prices_a_forced_hot_tin_and_never_a_forced_cold_etb(tmp_path, monkeypatch):
    w = make_watcher(tmp_path, products=[FORCED_COLD_ETB, FORCED_HOT_TIN])
    queried = []

    def fake_search(query, game, pin=None):
        queried.append(query)
        return {"market": 12.5, "name": "x", "product_id": 1}

    monkeypatch.setattr(watcher_mod.market_mod, "search", fake_search)

    for _ in range(2):  # the second tick would price the cold ETB if it were not skipped
        w.run_market_tick()

    assert len(queried) == 1
    assert "Tin" in queried[0]


def test_the_page_lists_a_forced_hot_tin_and_drops_a_forced_cold_etb(tmp_path, monkeypatch):
    monkeypatch.setattr(site_mod.ev, "match_group", lambda name: None)
    cfg = make_config(tmp_path, products=[FORCED_COLD_ETB, FORCED_HOT_TIN, PLAIN_ETB])

    names = [g["name"] for g in site_mod.collect(cfg)["groups"]]

    assert len(names) == 2
    assert any("Tin" in n for n in names)
    assert not any("Elite Trainer" in n for n in names)
