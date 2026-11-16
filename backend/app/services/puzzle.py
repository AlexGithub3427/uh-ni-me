"""The daily puzzle and a player's progress through it."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyPuzzle, Entity, Player, Prompt, PromptAnswer, Submission
from app.schemas.puzzle import PromptProgress


async def prompt_count(session: AsyncSession, day: date) -> int:
    """How many prompts ``day``'s puzzle has. 0 means there is no puzzle."""
    count = await session.scalar(
        select(func.count()).select_from(DailyPuzzle).where(DailyPuzzle.day == day)
    )
    return count or 0


def is_finished(submission: Submission, *, now: datetime, time_limit: timedelta) -> bool:
    """Whether a served prompt is finished for its player (CLAUDE.md, Game integrity).

    ``time_limit`` is the answer time limit plus grace.
    """
    return submission.outcome is not None or now > submission.started_at + time_limit


async def prompt_at(session: AsyncSession, day: date, position: int) -> Prompt | None:
    """The prompt at ``position`` of ``day``'s puzzle."""
    return await session.scalar(
        select(Prompt)
        .join(DailyPuzzle, DailyPuzzle.prompt_id == Prompt.id)
        .where(DailyPuzzle.day == day, DailyPuzzle.position == position)
    )


async def player_exists(session: AsyncSession, player_id: uuid.UUID) -> bool:
    return await session.get(Player, player_id) is not None


async def create_player(session: AsyncSession) -> uuid.UUID:
    """A new anonymous player (F-034). The caller commits."""
    player = Player()
    session.add(player)
    await session.flush()
    return player.id


async def submission_at(
    session: AsyncSession, player_id: uuid.UUID, day: date, position: int, *, lock: bool = False
) -> Submission | None:
    """The player's submission for the prompt at ``position``, if it was served.

    ``lock`` holds the row until the transaction ends, so two guesses sent at
    once are handled one after the other.
    """
    statement = (
        select(Submission)
        .join(
            DailyPuzzle,
            (DailyPuzzle.day == Submission.day) & (DailyPuzzle.prompt_id == Submission.prompt_id),
        )
        .where(
            Submission.player_id == player_id,
            Submission.day == day,
            DailyPuzzle.position == position,
        )
    )
    if lock:
        statement = statement.with_for_update(of=Submission)
    return await session.scalar(statement)


async def start_prompt(
    session: AsyncSession, player_id: uuid.UUID, day: date, prompt_id: int, *, now: datetime
) -> datetime:
    """Record that the prompt was served at ``now`` and return its start time.

    A prompt that was already served keeps its original start time, also when
    two requests race. The caller commits.
    """
    key = {"player_id": player_id, "day": day, "prompt_id": prompt_id}
    await session.execute(insert(Submission).values(**key, started_at=now).on_conflict_do_nothing())
    started_at = await session.scalar(select(Submission.started_at).filter_by(**key))
    assert started_at is not None
    return started_at


@dataclass(frozen=True)
class AnswerCounts:
    """What the scorer needs to know about an accepted answer (F-033)."""

    base_rarity: float
    times_answered: int
    most_answered: int
    total_answered: int


async def count_answer(session: AsyncSession, prompt_id: int, entity_id: int) -> AnswerCounts:
    """Count one more player giving this answer and return the prompt's counts.

    The counts include the answer just given.
    """
    row = (
        await session.execute(
            update(PromptAnswer)
            .where(PromptAnswer.prompt_id == prompt_id, PromptAnswer.entity_id == entity_id)
            .values(times_answered=PromptAnswer.times_answered + 1)
            .returning(PromptAnswer.base_rarity, PromptAnswer.times_answered)
        )
    ).one()
    most, total = (
        await session.execute(
            select(
                func.max(PromptAnswer.times_answered), func.sum(PromptAnswer.times_answered)
            ).where(PromptAnswer.prompt_id == prompt_id)
        )
    ).one()
    return AnswerCounts(
        base_rarity=row.base_rarity,
        times_answered=row.times_answered,
        most_answered=most,
        total_answered=total,
    )


@dataclass(frozen=True)
class ListedAnswer:
    """One valid answer of a prompt, with what the scorer needs for its current rarity."""

    name: str
    base_rarity: float
    times_answered: int


async def prompt_answers(session: AsyncSession, prompt_id: int) -> list[ListedAnswer]:
    """Every valid answer of the prompt, alphabetically by name, ignoring case (F-035)."""
    rows = await session.execute(
        select(Entity.canonical_name, PromptAnswer.base_rarity, PromptAnswer.times_answered)
        .join(Entity, Entity.id == PromptAnswer.entity_id)
        .where(PromptAnswer.prompt_id == prompt_id)
    )
    answers = [ListedAnswer(*row) for row in rows]
    # Sorted here, not by Postgres, so the order doesn't depend on the database's collation.
    return sorted(answers, key=lambda answer: (answer.name.casefold(), answer.name))


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
        if is_finished(submission, now=now, time_limit=time_limit):
            progress.append(
                PromptProgress(
                    position=position,
                    outcome=submission.outcome or "expired",
                    points=submission.points or 0,
                    rarity_tier=submission.rarity_tier,
                )
            )
    return progress
