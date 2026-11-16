"""Seed helpers shared by the gameplay API tests (F-030 onward)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.api.deps import get_now
from app.config import get_settings
from app.main import app
from app.models import (
    DailyPuzzle,
    Entity,
    EntityAlias,
    Player,
    Prompt,
    PromptAnswer,
    PromptTemplate,
    Submission,
)
from app.services.normalize import normalize
from tests.factories import make_anime

DAY = date(2026, 6, 1)
NOON = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def set_now(now: datetime) -> None:
    """Set the API's clock. The ``api_client`` fixture clears it after the test."""
    app.dependency_overrides[get_now] = lambda: now


def make_puzzle(session: Session, day: date, size: int = 7) -> list[Prompt]:
    """A puzzle of ``size`` prompts for ``day``, in position order."""
    template = PromptTemplate(
        slug=f"template-{day}", text="Name an anime by {studio}", answer_kind="anime", query_def={}
    )
    session.add(template)
    session.flush()
    prompts = [
        Prompt(template_id=template.id, params={"n": n}, text=f"Name an anime by studio {n}")
        for n in range(size)
    ]
    session.add_all(prompts)
    session.flush()
    session.add_all(
        DailyPuzzle(day=day, position=position, prompt_id=prompt.id)
        for position, prompt in enumerate(prompts, start=1)
    )
    session.flush()
    return prompts


def make_player(session: Session) -> uuid.UUID:
    player = Player()
    session.add(player)
    session.flush()
    return player.id


def start_prompt(
    session: Session,
    player_id: uuid.UUID,
    prompt: Prompt,
    started_at: datetime,
    *,
    day: date = DAY,
    outcome: str | None = None,
    points: int | None = None,
    rarity_tier: str | None = None,
    guess_count: int = 0,
) -> None:
    """A submission row as F-031/F-032 leave it. No ``outcome`` means still unanswered."""
    columns: dict[str, Any] = {}
    if outcome:
        columns = {"finished_at": started_at + timedelta(seconds=10), "outcome": outcome}
    if outcome == "accepted":
        columns["raw_text"] = "an answer"
        columns["matched_entity_id"] = make_anime(session, f"Answer to {prompt.id}").id
    session.add(
        Submission(
            player_id=player_id,
            day=day,
            prompt_id=prompt.id,
            started_at=started_at,
            points=points,
            rarity_tier=rarity_tier,
            guess_count=guess_count,
            **columns,
        )
    )
    session.flush()


def add_answer(
    session: Session, prompt: Prompt, entity: Entity, *aliases: str, base_rarity: float = 0.5
) -> Entity:
    """Make ``entity`` a valid answer for ``prompt``, typed as its name or any of ``aliases``."""
    # One alias per match key, as ingest stores them.
    by_key = {normalize(alias): alias for alias in (*aliases, entity.canonical_name)}
    session.add_all(
        EntityAlias(entity_id=entity.id, alias=alias, normalized=key)
        for key, alias in by_key.items()
    )
    session.add(PromptAnswer(prompt_id=prompt.id, entity_id=entity.id, base_rarity=base_rarity))
    session.flush()
    return entity


def time_limit() -> timedelta:
    """How long after a prompt is served it stays open (limit plus grace)."""
    settings = get_settings()
    return timedelta(seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds)
