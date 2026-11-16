"""Playing a day's prompts (F-031, F-032)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now, get_player_id
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Prompt
from app.schemas.play import Guess, GuessResult, PromptStart
from app.services import puzzle as puzzle_service
from app.services import scoring
from app.services.matching import match_answer

router = APIRouter()


async def _todays_prompt(
    session: AsyncSession, day: date, n: int, now: datetime, player_id: uuid.UUID | None
) -> tuple[Prompt, uuid.UUID]:
    """Prompt ``n`` of today's puzzle and the known player asking for it."""
    # TODO(F-052): archive mode serves past days.
    if day != now.astimezone(UTC).date():
        raise HTTPException(status_code=404, detail=f"{day} is not today's puzzle")
    prompt = await puzzle_service.prompt_at(session, day, n)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"No prompt {n} in the puzzle for {day}")
    # TODO(F-034): create the player on first visit instead of rejecting.
    if player_id is None or not await puzzle_service.player_exists(session, player_id):
        raise HTTPException(status_code=401, detail="Unknown player")
    return prompt, player_id


def _open_for(settings: Settings) -> timedelta:
    """How long after a prompt is served a guess is still taken: the limit plus grace."""
    return timedelta(seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds)


@router.post("/play/{day}/prompt/{n}/start")
async def start_prompt(
    day: date,
    n: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    player_id: Annotated[uuid.UUID | None, Depends(get_player_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PromptStart:
    """Serve prompt ``n`` and start its timer. Starting it again changes nothing."""
    prompt, player_id = await _todays_prompt(session, day, n, now, player_id)

    if n > 1:
        previous = await puzzle_service.submission_at(session, player_id, day, n - 1)
        if previous is None or not puzzle_service.is_finished(
            previous, now=now, time_limit=_open_for(settings)
        ):
            raise HTTPException(status_code=409, detail=f"Prompt {n - 1} is not finished")

    started_at = await puzzle_service.start_prompt(session, player_id, day, prompt.id, now=now)
    await session.commit()
    return PromptStart(
        position=n,
        text=prompt.text,
        started_at=started_at,
        deadline=started_at + timedelta(seconds=settings.answer_time_limit_seconds),
    )


@router.post("/play/{day}/prompt/{n}/answer")
async def submit_answer(
    day: date,
    n: int,
    guess: Guess,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    player_id: Annotated[uuid.UUID | None, Depends(get_player_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GuessResult:
    """Take one guess for prompt ``n``. The first valid guess is the player's answer."""
    prompt, player_id = await _todays_prompt(session, day, n, now, player_id)

    submission = await puzzle_service.submission_at(session, player_id, day, n, lock=True)
    if submission is None:
        raise HTTPException(status_code=409, detail=f"Prompt {n} has not been started")
    if submission.outcome == "accepted":
        raise HTTPException(status_code=409, detail=f"Prompt {n} is already answered")

    open_for = _open_for(settings)
    if puzzle_service.is_finished(submission, now=now, time_limit=open_for):
        # Too late: the guess is not matched.
        if submission.outcome is None:
            submission.outcome = "expired"
            submission.finished_at = submission.started_at + open_for
            submission.points = 0
            await session.commit()
        return GuessResult(accepted=False, finished=True)

    if submission.guess_count >= settings.max_guesses_per_prompt:
        raise HTTPException(status_code=429, detail=f"No guesses left for prompt {n}")
    submission.guess_count += 1

    entity = await match_answer(
        session, prompt.id, guess.text, threshold=settings.match_similarity_threshold
    )
    if entity is None:
        submission.wrong_guesses = [*submission.wrong_guesses, guess.text]
        await session.commit()
        return GuessResult(accepted=False, finished=False)

    base_rarity = await puzzle_service.count_answer(session, prompt.id, entity.id)
    # Stored now and never recomputed, however the answer's rarity moves later.
    tier, points = scoring.tier_and_points(base_rarity)
    result = GuessResult(
        accepted=True,
        finished=True,
        matched_name=entity.canonical_name,
        points=points,
        rarity_tier=tier,
    )
    submission.outcome = "accepted"
    submission.finished_at = now
    submission.raw_text = guess.text
    submission.matched_entity_id = entity.id
    submission.points = points
    submission.rarity_tier = tier
    await session.commit()
    return result
