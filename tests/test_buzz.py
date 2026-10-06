"""Mention counting (lifecycle.buzz): how often a product's set was mentioned in the deal subreddits this week.

Oracle (README "Hot first, stale last"): the score is "boosted by how many times the product's set was
mentioned in the deal subreddits this week (the flame count on the row)". lifecycle.set_phrase's
docstring gives the set: 'Prismatic Evolutions Booster Bundle' -> 'prismatic evolutions'.

"This week" is 7 days, so a mention one hour inside the window counts and one hour outside does not.
The README does not say whether exactly 7 days counts, so no case sits on the line. The README does
not say whether a longer word that contains the set name (such as "Prismatic Evolutionsx") counts, so
that is not asserted. Time comes from the conftest `clock`; titles are (timestamp, title) pairs as
feeds.recent_titles returns them.
"""
import pytest

from tcgwatch import lifecycle

DAY = 86_400
HOUR = 3_600

BOOSTER_BUNDLE = "Pokemon Prismatic Evolutions Booster Bundle"
RESTOCK_TITLE = "[Target] Prismatic Evolutions ETB back in stock $49.99"


def mention(clock, title, age_s=60):
    """A deal-subreddit title posted `age_s` seconds before the frozen now."""
    return (clock.now - age_s, title)


def test_mention_one_hour_inside_the_week_counts(clock):
    titles = [mention(clock, RESTOCK_TITLE, age_s=7 * DAY - HOUR)]

    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 1


def test_mention_one_hour_outside_the_week_does_not_count(clock):
    titles = [mention(clock, RESTOCK_TITLE, age_s=7 * DAY + HOUR)]

    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 0


def test_a_mention_stops_counting_once_the_clock_moves_it_out_of_the_week(clock):
    titles = [mention(clock, RESTOCK_TITLE, age_s=7 * DAY - HOUR)]
    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 1

    clock.advance(2 * HOUR)  # now the post is 7 days and 1 hour old

    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 0


def test_every_mention_in_the_week_counts_once(clock):
    titles = [
        mention(clock, "Prismatic Evolutions ETB at Target", age_s=60),
        mention(clock, "Prismatic Evolutions booster bundle at Walmart", age_s=2 * DAY),
        mention(clock, "Prismatic Evolutions ETB at GameStop", age_s=6 * DAY),
    ]

    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 3


@pytest.mark.parametrize(
    "title",
    [
        "prismatic evolutions restock",
        "PRISMATIC EVOLUTIONS RESTOCK",
        "Prismatic Evolutions restock",
        "prismatic   evolutions restock",
        "[Target] Pokemon Prismatic Evolutions ETB back in stock $49.99",
    ],
    ids=["lower", "upper", "title-case", "extra-spaces", "inside-a-sentence"],
)
def test_set_name_matches_in_any_case_and_inside_a_longer_title(clock, title):
    assert lifecycle.buzz(BOOSTER_BUNDLE, [mention(clock, title)]) == 1


@pytest.mark.parametrize(
    "title",
    ["Prismatic restock at Target", "Evolutions restock at Target", "Prism Evo restock at Target"],
    ids=["first-word-only", "second-word-only", "abbreviated"],
)
def test_a_post_with_only_part_of_the_set_name_does_not_count(clock, title):
    assert lifecycle.buzz(BOOSTER_BUNDLE, [mention(clock, title)]) == 0


def test_posts_about_another_set_do_not_count(clock):
    titles = [
        mention(clock, "Surging Sparks ETB at Target"),
        mention(clock, "Journey Together booster bundle at Walmart"),
        mention(clock, RESTOCK_TITLE),
    ]

    assert lifecycle.buzz(BOOSTER_BUNDLE, titles) == 1, "only the Prismatic Evolutions post"


def test_no_posts_means_no_mentions(clock):
    assert lifecycle.buzz(BOOSTER_BUNDLE, []) == 0


def test_a_product_name_with_no_set_in_it_counts_no_mentions(clock):
    # "Elite Trainer Box" names a product type, not a set, so no post can be a mention of its set.
    titles = [mention(clock, "Elite Trainer Box restock at Target")]

    assert lifecycle.buzz("Elite Trainer Box", titles) == 0
