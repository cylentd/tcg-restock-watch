"""Grouping, from README "Status page": products are grouped across retailers.

The same sealed product listed under different retailers' wordings shares one group key; a different
product, or the same words in a different game, does not. Names below follow config.yaml's style.
"""
import pytest

from tcgwatch import grouping


def same_group(a, b):
    return grouping.group_key(a) == grouping.group_key(b)


# --- what joins -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_name, bestbuy_name",
    [
        (
            "Pokemon Prismatic Evolutions Booster Bundle",
            "Pokemon Prismatic Evolutions Booster Bundle",
        ),
        (
            "Pokemon Prismatic Evolutions Elite Trainer Box",
            "Pokémon Trading Card Game: Prismatic Evolutions Elite Trainer Box",
        ),
        (
            "Pokemon Surging Sparks Elite Trainer Box",
            "POKEMON SURGING SPARKS ELITE TRAINER BOX",
        ),
        (
            "Pokemon Surging Sparks Elite Trainer Box",
            "Pokemon  Surging-Sparks Elite Trainer Box",
        ),
        (
            "Pokemon Destined Rivals Booster Bundle",
            "Pokemon Destined Rivals Booster Bundle (verify)",
        ),
    ],
    ids=["identical", "tcg-prefix-and-accent", "case", "spacing-and-hyphen", "verify-tag"],
)
def test_the_same_product_worded_differently_by_two_retailers_joins_one_group(target_name, bestbuy_name):
    assert same_group(target_name, bestbuy_name), f"{target_name!r} and {bestbuy_name!r} should group together"


# --- what stays apart -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("Pokemon Prismatic Evolutions Elite Trainer Box", "Pokemon Prismatic Evolutions Booster Bundle"),
        ("Pokemon Mega Evolution Elite Trainer Box", "Pokemon Mega Evolution Chaos Rising Elite Trainer Box"),
        ("Pokemon Surging Sparks Elite Trainer Box", "Pokemon Destined Rivals Elite Trainer Box"),
        ("Pokemon Prismatic Evolutions Super-Premium Collection", "Pokemon Prismatic Evolutions Elite Trainer Box"),
    ],
    ids=["etb-vs-bundle", "base-set-vs-expansion", "different-sets", "collection-vs-etb"],
)
def test_different_products_stay_in_separate_groups(a, b):
    assert not same_group(a, b), f"{a!r} and {b!r} must not group together"


def test_one_piece_and_pokemon_products_with_the_same_words_stay_apart():
    pokemon = "Pokemon Booster Box"
    one_piece = "One Piece Booster Box"

    assert not same_group(pokemon, one_piece)


def test_one_piece_and_riftbound_stay_apart_from_each_other():
    assert not same_group("One Piece Starter Deck", "Riftbound Starter Deck")


# --- which game a name belongs to -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name, game",
    [
        ("Pokemon Surging Sparks Elite Trainer Box", "Pokemon"),
        ("One Piece EB-03 Heroines Edition Booster Pack", "One Piece"),
        ("Bandai ST-31 Monkey.D.Luffy Starter Deck", "One Piece"),
        ("Riftbound Origins Booster Box", "Riftbound"),
        ("League of Legends TCG Starter Deck", "Riftbound"),
    ],
    ids=["pokemon", "one-piece-by-name", "one-piece-by-set-code", "riftbound", "league-of-legends"],
)
def test_game_is_read_from_the_product_name(name, game):
    assert grouping.game_of(name) == game


# --- the name the page shows ----------------------------------------------------------------------
# The page drops the leading game word (the game tag beside the name already says it), but "Pokemon
# Center" is the store-exclusive edition's name, not the game: without it "Center Mega Evolution Elite
# Trainer Box" reads as a typo of "Mega Evolution Elite Trainer Box" (QA, 2026-10-09).


@pytest.mark.parametrize(
    "name, shown",
    [
        ("Pokemon Mega Evolution Elite Trainer Box", "Mega Evolution Elite Trainer Box"),
        ("Pokemon Center Mega Evolution Elite Trainer Box", "Pokemon Center Mega Evolution Elite Trainer Box"),
        ("Pokémon Center 30th Celebration Elite Trainer Box", "Pokémon Center 30th Celebration Elite Trainer Box"),
        ("One Piece OP-09 Booster Box", "OP-09 Booster Box"),
        ("Riftbound Origins Booster Display", "Origins Booster Display"),
        ("Pokemon Destined Rivals Booster Bundle (bundle or box, verify)", "Destined Rivals Booster Bundle"),
    ],
    ids=["game-word-dropped", "pokemon-center-kept", "pokemon-center-accented", "one-piece", "riftbound",
         "verify-note-dropped"],
)
def test_the_shown_name_drops_the_game_word_but_keeps_pokemon_center(name, shown):
    assert grouping.display_name(name) == shown


def test_the_tcgplayer_query_for_a_pokemon_center_product_is_unchanged():
    # TCGplayer lists these as "Pokemon Center ..." under the Pokemon category; the query has always
    # been sent without the game word, and the market tick's saved matches depend on it.
    assert grouping.market_query("Pokemon Center Mega Evolution Elite Trainer Box") == "Center Mega Evolution Elite Trainer Box"


