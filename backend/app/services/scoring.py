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


def tier_and_points(rarity: float) -> tuple[str, int]:
    """The rarity tier of a valid answer with ``rarity`` (0-1) and the points it scores.

    A rarity exactly on a cutoff belongs to the rarer tier.
    """
    # TODO(F-033): blend times_answered into the rarity, and test each tier boundary.
    tier, _, points = max(
        (entry for entry in TIERS if rarity >= entry[1]), key=lambda entry: entry[1]
    )
    return tier, points
