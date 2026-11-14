"""Reads of the daily puzzle and a player's progress through it."""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPuzzle, Submission
from app.schemas.puzzle import PromptProgress


async def prompt_count(session: AsyncSession, day: date) -> int:
    """How many prompts ``day``'s puzzle has. 0 means there is no puzzle."""
    count = await session.scalar(
        select(func.count()).select_from(DailyPuzzle).where(DailyPuzzle.day == day)
    )
    return count or 0


async def player_progress(
    session: AsyncSession,
    player_id: uuid.UUID,
    day: date,
    *,
    now: datetime,
    time_limit: timedelta,
) -> list[PromptProgress]:
    """The player's finished prompts of ``day``, by position.

    ``time_limit`` is the answer time limit plus grace. A prompt served longer
    ago than that with no outcome yet is reported as expired. This is a read:
    the row itself is written by F-032 / F-035.
    """
    rows = await session.execute(
        select(DailyPuzzle.position, Submission)
        .join(
            DailyPuzzle,
            (DailyPuzzle.day == Submission.day) & (DailyPuzzle.prompt_id == Submission.prompt_id),
        )
        .where(Submission.player_id == player_id, Submission.day == day)
        .order_by(DailyPuzzle.position)
    )
    progress = []
    for position, submission in rows:
        outcome = submission.outcome
        if outcome is None and now > submission.started_at + time_limit:
            outcome = "expired"
        if outcome is not None:
            progress.append(
                PromptProgress(
                    position=position,
                    outcome=outcome,
                    points=submission.points or 0,
                    rarity_tier=submission.rarity_tier,
                )
            )
    return progress
