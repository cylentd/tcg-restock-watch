"""The retire limits reach the watcher: config defaults, then the product filter that uses them.

Oracle (README "Hot first, stale last"): "A product retires when no retailer has had it in stock for
`retire_after_days` (60) since first seen, or when every retailer has delisted it for
`retire_missing_days` (7). Retired products stop being polled." The rule itself is tested in
test_lifecycle.py; here the defaults are the 60 and 7 the README states, and Watcher.active_products
drops a retired product. Boundaries sit one hour either side of the limit, where every reading
of "more than" agrees. The clock is the frozen one from conftest.
"""

import pytest

from tcgwatch import config as config_mod
from tcgwatch.config import Product
from tests.builders import make_config, make_watcher

DAY = 86_400
HOUR = 3_600


# -- defaults ----------------------------------------------------------------------------------


def test_config_file_without_retire_keys_loads_the_readme_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"data_dir: '{tmp_path.as_posix()}'\nproducts: []\n", encoding="utf-8")

    cfg = config_mod.load(config_file)

    assert (cfg.retire_after_days, cfg.retire_missing_days) == (60, 7), "README: retire_after_days (60), retire_missing_days (7)"


def test_config_built_in_code_without_retire_fields_has_the_readme_defaults(tmp_path):
    cfg = make_config(tmp_path)

    assert (cfg.retire_after_days, cfg.retire_missing_days) == (60, 7), "README: retire_after_days (60), retire_missing_days (7)"


def test_config_file_can_override_the_retire_limits(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"data_dir: '{tmp_path.as_posix()}'\nproducts: []\nretire_after_days: 30\nretire_missing_days: 3\n", encoding="utf-8"
    )

    cfg = config_mod.load(config_file)

    assert (cfg.retire_after_days, cfg.retire_missing_days) == (30, 3)


# -- the watcher's product filter ------------------------------------------------------------------

ETB = Product("target", "1", "Pokemon Elite Trainer Box Alpha", msrp=49.99)


def seconds_ago(clock, seconds):
    return None if seconds is None else clock.now - seconds


@pytest.mark.parametrize(
    "first_seen_ago, last_in_stock_ago, missing_ago, still_polled",
    [
        (60 * DAY - HOUR, None, None, True),                      # never in stock, just under 60 days
        (60 * DAY + HOUR, None, None, False),                     # never in stock, just over 60 days
        (20 * DAY, 15 * DAY, 7 * DAY - HOUR, True),               # delisted just under 7 days
        (20 * DAY, 15 * DAY, 7 * DAY + HOUR, False),              # delisted just over 7 days
    ],
    ids=["just-under-60d-dry", "just-over-60d-dry", "just-under-7d-delisted", "just-over-7d-delisted"],
)
def test_watcher_polls_a_product_until_the_default_retire_limits_pass(
    tmp_path, clock, first_seen_ago, last_in_stock_ago, missing_ago, still_polled
):
    w = make_watcher(tmp_path, products=[ETB])
    w.state.update(
        ETB.key,
        first_seen=seconds_ago(clock, first_seen_ago),
        last_in_stock=seconds_ago(clock, last_in_stock_ago),
        missing_since=seconds_ago(clock, missing_ago),
    )

    polled = w.active_products("target")

    assert (ETB in polled) is still_polled, (
        f"first seen {first_seen_ago / DAY:.2f}d ago, last in stock {last_in_stock_ago}, missing {missing_ago}: "
        f"expected polled={still_polled}"
    )


def test_watcher_uses_the_configured_retire_limit_not_a_built_in_one(tmp_path, clock):
    w = make_watcher(tmp_path, products=[ETB], retire_after_days=10)
    w.state.update(ETB.key, first_seen=clock.now - 11 * DAY)  # inside the default 60, past the configured 10

    polled = w.active_products("target")

    assert polled == [], "a product dry for 11 days must stop being polled when retire_after_days is 10"


def test_a_retired_product_does_not_stop_its_siblings_from_being_polled(tmp_path, clock):
    live = Product("target", "2", "Pokemon Booster Bundle Beta", msrp=26.94)
    w = make_watcher(tmp_path, products=[ETB, live])
    w.state.update(ETB.key, first_seen=clock.now - 61 * DAY)
    w.state.update(live.key, first_seen=clock.now - 2 * DAY)

    polled = w.active_products("target")

    assert polled == [live]
