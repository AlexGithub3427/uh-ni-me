"""Response bodies for the daily puzzle (F-030)."""

from datetime import date

from pydantic import BaseModel


class PromptProgress(BaseModel):
    """The player's result for one finished prompt."""

    position: int
    outcome: str  # "accepted" or "expired"
    points: int
    rarity_tier: str | None  # None unless accepted


class PuzzleToday(BaseModel):
    day: date
    prompt_count: int
    # Finished prompts only, by position. The next one to play is len(progress) + 1.
    progress: list[PromptProgress]
