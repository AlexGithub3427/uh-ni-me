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


# TODO(F-033): rarity tiers, points and the times_answered blend.
