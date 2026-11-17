"""Request and response bodies for playing a prompt (F-031, F-032, F-035)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

# No anime or character name comes close to this.
MAX_GUESS_LENGTH = 200


class PromptStart(BaseModel):
    """A served prompt. Never its answers."""

    position: int
    text: str
    # Server time. ``deadline`` is ``started_at`` plus the answer time limit, without the grace.
    started_at: datetime
    deadline: datetime
    # When the server answered. The time left is ``deadline`` minus ``now``, so the client's
    # countdown never reads the player's clock, also when it resumes a started prompt.
    now: datetime


class Guess(BaseModel):
    """One typed answer. Blank text is not a guess."""

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_GUESS_LENGTH)
    ]


class GuessResult(BaseModel):
    """What a guess did. Never the prompt's other answers.

    ``finished`` without ``accepted`` means the prompt ran out of time.
    """

    accepted: bool
    finished: bool
    matched_name: str | None = None
    points: int = 0
    rarity_tier: str | None = None


class ValidAnswer(BaseModel):
    """One of a prompt's valid answers, with the tier it would score now."""

    name: str
    rarity_tier: str


class PromptResult(BaseModel):
    """A finished prompt: what the player scored and every valid answer (F-035).

    ``points`` and ``rarity_tier`` are the player's, as stored when they answered. The
    tiers in ``answers`` are current, so the player's own answer may have moved since.
    """

    outcome: str
    matched_name: str | None = None
    points: int = 0
    rarity_tier: str | None = None
    answers: list[ValidAnswer]
