"""Rarity scoring: pure functions, no database."""

import pytest

from app.models import RARITY_TIERS
from app.services.scoring import TIERS, base_rarities, tier_and_points


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
