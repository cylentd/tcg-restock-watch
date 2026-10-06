"""Hot score, from README "Hot first, stale last".

score = premium x type weight x subreddit-mention boost; in stock x3 only when premium >= 1.3,
else x1.3 (unpriced or at MSRP counts as unproven); in stock within 7 days x1.5, or x1.1 unproven.
Type weights: booster boxes and premium collections 1.3, ETBs 1.2, blisters and tins 0.8, decks 0.6.

Expected values are worked by hand in each case's comment, with no mentions (buzz 0) so the boost is 1.
The README gives no number for the mention boost, so that test asserts only the direction.
The README does not say whether exactly 7 days counts as recent, so the cases sit an hour either side.
Time is the conftest `clock`: NOW is its frozen instant.
"""
import pytest

from tcgwatch import lifecycle
from tests.conftest import CLOCK_START

NOW = CLOCK_START
DAY = 86_400
HOUR = 3_600

ETB = "Pokemon Prismatic Evolutions Elite Trainer Box"
BATTLE_DECK = "Pokemon Mega Lucario ex League Battle Deck"
BOOSTER_BOX = "Pokemon Surging Sparks Booster Box"
TIN = "Pokemon 30th Celebration Tin"


def score(name, premium, in_stock, last_in_stock=None, buzz=0):
    return lifecycle.hot_score(premium, buzz, last_in_stock, in_stock, name)


# --- the README's own example --------------------------------------------------------------------


def test_unpriced_battle_deck_in_stock_does_not_outrank_a_scalped_etb_that_is_sold_out():
    deck_in_stock = score(BATTLE_DECK, premium=None, in_stock=True)  # 1.0 x 0.6 x 1.3 = 0.78
    etb_scalped = score(ETB, premium=1.5, in_stock=False)  # 1.5 x 1.2 = 1.8, never in stock

    assert deck_in_stock == pytest.approx(0.78)
    assert etb_scalped == pytest.approx(1.8)
    assert deck_in_stock < etb_scalped


# --- in stock: x3 only at premium >= 1.3 ---------------------------------------------------------


def test_in_stock_at_premium_1_3_triples_the_score():
    # 1.3 x 1.3 (booster box) x 3 = 5.07
    assert score(BOOSTER_BOX, premium=1.3, in_stock=True) == pytest.approx(5.07)


def test_in_stock_just_below_premium_1_3_gets_only_the_small_nudge():
    # 1.29 x 1.3 (booster box) x 1.3 = 2.1801
    assert score(BOOSTER_BOX, premium=1.29, in_stock=True) == pytest.approx(2.1801, abs=1e-3)


def test_in_stock_at_msrp_gets_the_small_nudge():
    # 1.0 x 1.2 (ETB) x 1.3 = 1.56
    assert score(ETB, premium=1.0, in_stock=True) == pytest.approx(1.56)


def test_in_stock_with_no_price_scores_as_premium_one_with_the_nudge():
    # 1.0 x 1.2 (ETB) x 1.3 = 1.56, same as at MSRP
    assert score(ETB, premium=None, in_stock=True) == pytest.approx(1.56)


# --- recently in stock (7 days) -------------------------------------------------------------------


def test_sold_out_one_hour_inside_a_week_with_proven_premium_gets_1_5x():
    # 1.5 x 0.8 (tin) x 1.5 = 1.8
    assert score(TIN, premium=1.5, in_stock=False, last_in_stock=NOW - (7 * DAY - HOUR)) == pytest.approx(1.8)


def test_sold_out_one_hour_inside_a_week_without_proven_premium_gets_1_1x():
    # 1.1 x 0.8 (tin) x 1.1 = 0.968
    assert score(TIN, premium=1.1, in_stock=False, last_in_stock=NOW - (7 * DAY - HOUR)) == pytest.approx(0.968)


def test_sold_out_one_hour_outside_a_week_gets_no_recency_boost():
    # 1.5 x 0.8 (tin) = 1.2
    assert score(TIN, premium=1.5, in_stock=False, last_in_stock=NOW - (7 * DAY + HOUR)) == pytest.approx(1.2)


def test_recency_boost_ends_when_the_clock_moves_the_last_stock_out_of_the_week(clock):
    last_in_stock = NOW - (7 * DAY - HOUR)
    assert score(TIN, premium=1.5, in_stock=False, last_in_stock=last_in_stock) == pytest.approx(1.8)

    clock.advance(2 * HOUR)  # last in stock is now 7 days and 1 hour ago

    assert score(TIN, premium=1.5, in_stock=False, last_in_stock=last_in_stock) == pytest.approx(1.2)


def test_never_in_stock_and_unpriced_scores_the_bare_type_weight():
    # 1.0 x 1.2 (ETB) = 1.2
    assert score(ETB, premium=None, in_stock=False, last_in_stock=None) == pytest.approx(1.2)


# --- type weights (premium 2.0, sold out, no history: score = 2.0 x weight) ----------------------


@pytest.mark.parametrize(
    "name, weight",
    [
        ("Pokemon Surging Sparks Booster Box", 1.3),
        ("Pokemon Charizard ex Premium Collection", 1.3),
        ("Pokemon Prismatic Evolutions Super-Premium Collection", 1.3),
        ("Pokemon Elite Trainer Box", 1.2),
        ("Pokemon Prismatic Evolutions 2-Pack Blister", 0.8),
        ("Pokemon 30th Celebration Tin", 0.8),
        ("Pokemon Mega Lucario ex League Battle Deck", 0.6),
    ],
    ids=["booster-box", "premium-collection", "super-premium-collection", "etb", "blister", "tin", "deck"],
)
def test_product_type_weights_the_premium(name, weight):
    assert score(name, premium=2.0, in_stock=False) == pytest.approx(2.0 * weight), f"weight for {name!r}"


# --- subreddit mentions ---------------------------------------------------------------------------


def test_more_subreddit_mentions_raise_the_score():
    quiet = score(ETB, premium=1.5, in_stock=False, buzz=0)
    buzzing = score(ETB, premium=1.5, in_stock=False, buzz=3)

    assert buzzing > quiet
