"""Playing a day's prompts (F-031)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now, get_player_id
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.play import PromptStart
from app.services import puzzle as puzzle_service

router = APIRouter()


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
    # TODO(F-052): archive mode serves past days.
    if day != now.astimezone(UTC).date():
        raise HTTPException(status_code=404, detail=f"{day} is not today's puzzle")
    prompt = await puzzle_service.prompt_at(session, day, n)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"No prompt {n} in the puzzle for {day}")
    # TODO(F-034): create the player on first visit instead of rejecting.
    if player_id is None or not await puzzle_service.player_exists(session, player_id):
        raise HTTPException(status_code=401, detail="Unknown player")

    if n > 1:
        previous = await puzzle_service.submission_at(session, player_id, day, n - 1)
        open_for = timedelta(
            seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds
        )
        if previous is None or not puzzle_service.is_finished(
            previous, now=now, time_limit=open_for
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
