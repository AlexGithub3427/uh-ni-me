"""Rarity scoring. Every rarity formula lives here, as pure functions."""

import math
from collections.abc import Sequence


def base_rarities(popularities: Sequence[int]) -> list[float]:
    """The ``base_rarity`` of each answer in one prompt, in the order given (F-021).

    A log-scaled inverse of popularity, normalized within the prompt: the most
    popular answer gets 0, the least popular gets 1, and the rest fall between
    by ``log(1 + popularity)``. If every answer is equally popular there is no
    scale to place them on, so they all get the midpoint, 0.5.
    """
    logs = [math.log1p(max(popularity, 0)) for popularity in popularities]
    if not logs:
        return []
    low, high = min(logs), max(logs)
    if high == low:
        return [0.5] * len(logs)
    return [(high - log) / (high - low) for log in logs]


# (tier, lowest rarity in the tier, points), most common to rarest. The cutoffs
# are placeholders to tune after playtesting (F-033).
TIERS: tuple[tuple[str, float, int], ...] = (
    ("larp", 0.0, 10),
    ("normie", 0.2, 30),
    ("niche", 0.4, 60),
    ("weeb", 0.6, 85),
    ("uh-ni-me", 0.8, 100),
)
# A prompt with no valid answer: left blank, only wrong guesses, or expired.
NO_ANSWER_POINTS = 0
# How much what players answer can outweigh popularity, at most, and how many
# accepted answers past the minimum it takes to get halfway there. Deliberately
# slow; tune after playtesting (F-033).
BLEND_MAX_WEIGHT = 0.5
BLEND_HALF_WEIGHT_SUBMISSIONS = 500


def blended_rarity(
    base_rarity: float,
    *,
    times_answered: int,
    most_answered: int,
    total_answered: int,
    min_submissions: int,
) -> float:
    """The rarity (0-1) of one answer: ``base_rarity`` blended with what players answer (F-033).

    ``times_answered`` is how often this answer was given, ``most_answered`` the
    count of the prompt's most-given answer and ``total_answered`` the count of
    all its accepted answers. Below ``min_submissions`` accepted answers there is
    too little data and the rarity is ``base_rarity`` alone.

    The observed rarity mirrors ``base_rarities``: a log-scaled inverse of
    ``times_answered``, 0 for the most-given answer and 1 for one nobody gave. Its
    weight starts at 0 at ``min_submissions`` and grows slowly toward
    ``BLEND_MAX_WEIGHT``, which it never passes: it is halfway there
    ``BLEND_HALF_WEIGHT_SUBMISSIONS`` answers past the minimum.
    """
    if total_answered < min_submissions or most_answered <= 0:
        return base_rarity
    observed = 1 - math.log1p(times_answered) / math.log1p(most_answered)
    extra = total_answered - min_submissions
    weight = BLEND_MAX_WEIGHT * extra / (extra + BLEND_HALF_WEIGHT_SUBMISSIONS)
    blended = (1 - weight) * base_rarity + weight * observed
    return min(max(blended, 0.0), 1.0)


def tier_and_points(rarity: float | None) -> tuple[str | None, int]:
    """The rarity tier of a valid answer with ``rarity`` (0-1) and the points it scores.

    A rarity exactly on a cutoff belongs to the rarer tier. ``None`` is no valid
    answer: no tier and no points.
    """
    if rarity is None:
        return None, NO_ANSWER_POINTS
    tier, _, points = max(
        (entry for entry in TIERS if rarity >= entry[1]), key=lambda entry: entry[1]
    )
    return tier, points
