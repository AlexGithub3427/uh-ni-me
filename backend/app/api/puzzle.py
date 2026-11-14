"""The daily puzzle endpoint (F-030)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now, get_player_id
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.puzzle import PuzzleToday
from app.services import puzzle as puzzle_service

router = APIRouter()


@router.get("/puzzle/today")
async def puzzle_today(
    session: Annotated[AsyncSession, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    player_id: Annotated[uuid.UUID | None, Depends(get_player_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PuzzleToday:
    """Today's puzzle metadata and the player's progress. Never prompt text or answers."""
    day = now.astimezone(UTC).date()
    count = await puzzle_service.prompt_count(session, day)
    if count == 0:
        raise HTTPException(status_code=404, detail=f"No puzzle for {day}")

    progress = []
    if player_id is not None:
        progress = await puzzle_service.player_progress(
            session,
            player_id,
            day,
            now=now,
            time_limit=timedelta(
                seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds
            ),
        )
    return PuzzleToday(day=day, prompt_count=count, progress=progress)
