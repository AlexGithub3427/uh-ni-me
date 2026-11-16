"""Rarity scoring: pure functions, no database."""

import pytest

from app.models import RARITY_TIERS
from app.services.scoring import TIERS, base_rarities, blended_rarity, tier_and_points


def test_f021_base_rarity_runs_from_most_popular_to_least_popular() -> None:
    assert base_rarities([5000, 300, 20]) == pytest.approx([0.0, 0.51, 1.0], abs=0.01)


def test_f021_base_rarity_is_log_scaled() -> None:
    # log(1 + popularity) is 2, 1 and 0 in base 10, so the middle answer sits halfway.
    assert base_rarities([99, 9, 0]) == pytest.approx([0.0, 0.5, 1.0])


def test_f021_base_rarity_keeps_the_order_of_its_input() -> None:
    assert base_rarities([0, 99, 9]) == pytest.approx([1.0, 0.0, 0.5])


def test_f021_base_rarity_is_per_entry_so_equal_popularity_means_equal_rarity() -> None:
    first, second, third = base_rarities([99, 9, 9])
    assert second == third
    assert first < second


def test_f021_base_rarity_is_the_midpoint_when_every_answer_is_equally_popular() -> None:
    assert base_rarities([40, 40, 40]) == [0.5, 0.5, 0.5]


def test_f021_base_rarity_of_no_answers_is_empty() -> None:
    assert base_rarities([]) == []


@pytest.mark.parametrize(
    ("rarity", "tier", "points"),
    [
        (0.1, "larp", 10),
        (0.3, "normie", 30),
        (0.5, "niche", 60),
        (0.7, "weeb", 85),
        (0.9, "uh-ni-me", 100),
    ],
)
def test_f032_an_accepted_answer_gets_the_tier_and_points_of_its_rarity(
    rarity: float, tier: str, points: int
) -> None:
    assert tier_and_points(rarity) == (tier, points)


def test_f032_scoring_tiers_are_the_ones_the_schema_allows() -> None:
    assert tuple(tier for tier, _, _ in TIERS) == RARITY_TIERS


def test_f033_no_valid_answer_scores_zero() -> None:
    assert tier_and_points(None) == (None, 0)


@pytest.mark.parametrize(
    ("rarity", "tier", "points"),
    [
        (0.0, "larp", 10),
        (0.1999, "larp", 10),
        (0.2, "normie", 30),
        (0.3999, "normie", 30),
        (0.4, "niche", 60),
        (0.5999, "niche", 60),
        (0.6, "weeb", 85),
        (0.7999, "weeb", 85),
        (0.8, "uh-ni-me", 100),
        (1.0, "uh-ni-me", 100),
    ],
)
def test_f033_a_rarity_on_a_cutoff_is_in_the_rarer_tier_and_one_just_below_is_not(
    rarity: float, tier: str, points: int
) -> None:
    assert tier_and_points(rarity) == (tier, points)


def test_f033_tier_cutoffs_and_points_are_the_documented_table() -> None:
    assert TIERS == (
        ("larp", 0.0, 10),
        ("normie", 0.2, 30),
        ("niche", 0.4, 60),
        ("weeb", 0.6, 85),
        ("uh-ni-me", 0.8, 100),
    )


def test_f033_the_most_a_seven_prompt_day_can_score_is_700() -> None:
    assert 7 * max(points for _, _, points in TIERS) == 700


def blend(base_rarity: float, times_answered: int, most_answered: int, total: int) -> float:
    return blended_rarity(
        base_rarity,
        times_answered=times_answered,
        most_answered=most_answered,
        total_answered=total,
        min_submissions=50,
    )


def test_f033_rarity_is_the_base_rarity_below_the_minimum_submissions() -> None:
    assert blend(0.9, times_answered=40, most_answered=40, total=49) == 0.9


def test_f033_the_blend_starts_from_a_weight_of_zero_at_the_minimum_submissions() -> None:
    assert blend(0.9, times_answered=40, most_answered=40, total=50) == pytest.approx(0.9)


def test_f033_rarity_blends_in_times_answered_past_the_minimum_submissions() -> None:
    # The most-given answer has an observed rarity of 0. 500 answers past the
    # minimum weigh it at half the maximum weight: 0.25.
    assert blend(0.9, times_answered=300, most_answered=300, total=550) == pytest.approx(0.675)


def test_f033_an_answer_nobody_gave_has_an_observed_rarity_of_one() -> None:
    assert blend(0.1, times_answered=0, most_answered=300, total=550) == pytest.approx(0.325)


def test_f033_observed_rarity_is_log_scaled_like_the_base_rarity() -> None:
    # log(1 + times_answered) is 1 of 2 in base 10: halfway, so 0.5 observed.
    assert blend(0.5, times_answered=9, most_answered=99, total=550) == pytest.approx(0.5)
    assert blend(0.0, times_answered=9, most_answered=99, total=550) == pytest.approx(0.125)


def test_f033_observed_answers_weigh_more_as_submissions_grow() -> None:
    # Base rarity 1 and observed rarity 0, so the rarity is 1 - weight.
    rarities = [
        blend(1.0, times_answered=total, most_answered=total, total=total)
        for total in (50, 150, 550, 1550)
    ]
    assert rarities == pytest.approx([1.0, 11 / 12, 0.75, 0.625])


def test_f033_observed_answers_never_weigh_more_than_the_base_rarity() -> None:
    total = 10**9
    rarity = blend(1.0, times_answered=total, most_answered=total, total=total)
    assert rarity >= 0.5
    assert rarity == pytest.approx(0.5, abs=1e-6)


def test_f033_blended_rarity_stays_between_0_and_1() -> None:
    for base in (0.0, 1.0):
        for times in (0, 1, 500):
            assert 0.0 <= blend(base, times_answered=times, most_answered=500, total=900) <= 1.0
