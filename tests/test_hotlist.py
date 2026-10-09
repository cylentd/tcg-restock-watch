"""Unit tests for the hot-item rule (tcgwatch/hotlist.py), judged against README "Hot items".

Oracle: hot = booster bundle, ETB, booster box or display, premium collection (incl. super and
ultra), special collection, illustration box, One Piece premium card collection, Riftbound
display. Not hot: double packs, single packs, blisters, tins, decks, anything unmatched. Every
name below is a product name copied from config.yaml, labeled by hand against that list.
"""

from __future__ import annotations

import pytest

from tcgwatch.hotlist import is_hot


@pytest.mark.parametrize(
    "name",
    [
        "Pokemon Prismatic Evolutions Booster Bundle",            # booster bundle
        "Pokemon 30th Celebration Booster Bundle",
        "Pokemon 30th Celebration Elite Trainer Box",             # ETB
        "Pokemon Center Mega Evolution Elite Trainer Box (Mega Lucario)",
        "Pokemon Elite Trainer Box + Poke Ball (Sam's Club)",
        "Pokemon Mega Evolution Chaos Rising Booster Box",        # booster box
        "Riftbound Unleashed Booster Display",                    # Riftbound display
        "Pokemon Mega Greninja ex Premium Collection",            # premium collection
        "Pokemon Sea & Sky Premium Collection Crown Zenith",
        "Pokemon Prismatic Evolutions Super-Premium Collection",
        "Pokemon Mega Charizard X ex Ultra-Premium Collection",
        "One Piece Illustration Box Vol. 7 (IB-07)",              # illustration box
        "One Piece Illustration Box 03",
        "One Piece Premium Card Collection Live Action vol.2",    # One Piece premium card collection
        "Pokemon Charizard ex Special Collection",                # special collection
        "POKEMON ELITE TRAINER BOX",                              # case does not matter
    ],
)
def test_hot_products_are_hot(name):
    assert is_hot(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "One Piece Double Pack 7 - A Fist of Divine Speed",       # double pack
        "Pokemon Mega Evolution Pitch Black Sleeved Booster",     # single pack
        "One Piece EB-03 Heroines Edition Booster Pack",
        "Riftbound Spiritforged Sleeved Booster Pack",
        "Pokemon Prismatic Evolutions 2-Pack Blister",            # blister
        "Pokemon Journey Together Blister",
        "Pokemon 30th Celebration Tin",                           # tin
        "Pokemon Mega Moonlit Tin Mega Gengar ex",
        "Pokemon 30th Celebration Mini Tins (10-Pack)",
        "Pokemon Mega Lucario ex League Battle Deck",             # deck
        "One Piece ST-31 Monkey.D.Luffy Starter Deck",
        "Riftbound Unleashed Champion Deck Vi",
        "Pokemon Quaquaval ex / Meowscarada ex Deluxe Battle Deck",
        "Pokemon 30th Celebration Knock Out Collection",          # unmatched collection
        "Pokemon 30th Celebration Poster Collection",
        "Pokemon Collector Chest Fall 2025",                      # unmatched
        "Riftbound Proving Grounds Starter Set",
        "Riftbound Unleashed Vault Bundle",                       # bundle, but not a booster bundle
        "Pokemon Destined Rivals Booster (bundle or box, verify)",  # ambiguous: not matched
        "Pokemon Premium Collection Tin",                         # an excluded type wins over a hot word
        "",
    ],
)
def test_other_products_are_not_hot(name):
    assert is_hot(name) is False
