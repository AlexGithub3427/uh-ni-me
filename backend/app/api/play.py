"""Playing a day's prompts (F-031, F-032, F-033, F-035) as an anonymous player (F-034)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PLAYER_COOKIE, PLAYER_COOKIE_MAX_AGE, get_now, get_player_id
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Entity, Prompt, Submission
from app.schemas.play import Guess, GuessResult, PromptResult, PromptStart, ValidAnswer
from app.services import puzzle as puzzle_service
from app.services import scoring
from app.services.matching import match_answer

router = APIRouter()


async def _todays_prompt(
    session: AsyncSession, day: date, n: int, now: datetime, player_id: uuid.UUID | None
) -> tuple[Prompt, uuid.UUID | None]:
    """Prompt ``n`` of today's puzzle and the player asking for it.

    The player is None when the cookie is missing, malformed or names no ``player`` row.
    """
    # TODO(F-052): archive mode serves past days.
    if day != now.astimezone(UTC).date():
        raise HTTPException(status_code=404, detail=f"{day} is not today's puzzle")
    prompt = await puzzle_service.prompt_at(session, day, n)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"No prompt {n} in the puzzle for {day}")
    if player_id is not None and not await puzzle_service.player_exists(session, player_id):
        player_id = None
    return prompt, player_id


def _open_for(settings: Settings) -> timedelta:
    """How long after a prompt is served a guess is still taken: the limit plus grace."""
    return timedelta(seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds)


async def _expire_if_unanswered(
    session: AsyncSession, submission: Submission, open_for: timedelta
) -> None:
    """Write ``expired`` to a submission that ran out of time with no accepted answer.

    The caller has checked that the prompt is finished and holds the row lock.
    """
    if submission.outcome is None:
        submission.outcome = "expired"
        # When the time ran out, not when the server noticed.
        submission.finished_at = submission.started_at + open_for
        submission.points = scoring.NO_ANSWER_POINTS
        await session.commit()


@router.post("/play/{day}/prompt/{n}/start")
async def start_prompt(
    day: date,
    n: int,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    player_id: Annotated[uuid.UUID | None, Depends(get_player_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PromptStart:
    """Serve prompt ``n`` and start its timer. Starting it again changes nothing.

    A visitor without a known player gets one here, with its cookie (F-034).
    """
    prompt, player_id = await _todays_prompt(session, day, n, now, player_id)

    if n > 1:
        previous = (
            await puzzle_service.submission_at(session, player_id, day, n - 1)
            if player_id is not None
            else None
        )
        if previous is None or not puzzle_service.is_finished(
            previous, now=now, time_limit=_open_for(settings)
        ):
            raise HTTPException(status_code=409, detail=f"Prompt {n - 1} is not finished")

    if player_id is None:
        # Created only once the request is sure to succeed, in the same transaction as
        # the submission, so a rejected request leaves no player without a cookie.
        player_id = await puzzle_service.create_player(session)
        response.set_cookie(
            PLAYER_COOKIE,
            str(player_id),
            max_age=PLAYER_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="lax",
        )

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

    if player_id is None:
        # Players are created by starting a prompt (F-034), never by a guess.
        raise HTTPException(status_code=401, detail="Unknown player")

    submission = await puzzle_service.submission_at(session, player_id, day, n, lock=True)
    if submission is None:
        raise HTTPException(status_code=409, detail=f"Prompt {n} has not been started")
    if submission.outcome == "accepted":
        raise HTTPException(status_code=409, detail=f"Prompt {n} is already answered")

    open_for = _open_for(settings)
    if puzzle_service.is_finished(submission, now=now, time_limit=open_for):
        # Too late: the guess is not matched.
        await _expire_if_unanswered(session, submission, open_for)
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

    counts = await puzzle_service.count_answer(session, prompt.id, entity.id)
    rarity = scoring.blended_rarity(
        counts.base_rarity,
        times_answered=counts.times_answered,
        most_answered=counts.most_answered,
        total_answered=counts.total_answered,
        min_submissions=settings.scoring_blend_min_submissions,
    )
    # Stored now and never recomputed, however the answer's rarity moves later.
    tier, points = scoring.tier_and_points(rarity)
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


@router.get("/play/{day}/prompt/{n}/result")
async def prompt_result(
    day: date,
    n: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    player_id: Annotated[uuid.UUID | None, Depends(get_player_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PromptResult:
    """The player's outcome for a finished prompt ``n``, and every valid answer to it."""
    prompt, player_id = await _todays_prompt(session, day, n, now, player_id)

    if player_id is None:
        # Without a player nothing was started, so nothing is finished (F-034).
        raise HTTPException(status_code=401, detail="Unknown player")

    # Locked, so a guess being accepted at this moment is not overwritten as expired.
    submission = await puzzle_service.submission_at(session, player_id, day, n, lock=True)
    if submission is None:
        raise HTTPException(status_code=409, detail=f"Prompt {n} has not been started")
    open_for = _open_for(settings)
    if not puzzle_service.is_finished(submission, now=now, time_limit=open_for):
        raise HTTPException(status_code=409, detail=f"Prompt {n} is not finished")
    await _expire_if_unanswered(session, submission, open_for)
    matched = (
        await session.get(Entity, submission.matched_entity_id)
        if submission.matched_entity_id is not None
        else None
    )
    return PromptResult(
        outcome=submission.outcome,
        matched_name=matched.canonical_name if matched else None,
        points=submission.points or scoring.NO_ANSWER_POINTS,
        rarity_tier=submission.rarity_tier,
        answers=_with_current_tiers(
            await puzzle_service.prompt_answers(session, prompt.id), settings
        ),
    )


def _with_current_tiers(
    answers: list[puzzle_service.ListedAnswer], settings: Settings
) -> list[ValidAnswer]:
    """Each answer with the tier it would score if it were given now."""
    counts = [answer.times_answered for answer in answers]
    most_answered, total_answered = max(counts, default=0), sum(counts)
    listed = []
    for answer in answers:
        rarity = scoring.blended_rarity(
            answer.base_rarity,
            times_answered=answer.times_answered,
            most_answered=most_answered,
            total_answered=total_answered,
            min_submissions=settings.scoring_blend_min_submissions,
        )
        tier, _ = scoring.tier_and_points(rarity)
        assert tier is not None  # a rarity always has a tier
        listed.append(ValidAnswer(name=answer.name, rarity_tier=tier))
    return listed
