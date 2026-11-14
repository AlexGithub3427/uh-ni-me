"""GET /api/puzzle/today (F-030)."""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import PLAYER_COOKIE, get_now
from app.config import get_settings
from app.main import app
from app.models import DailyPuzzle, Player, Prompt, PromptTemplate, Submission
from tests.factories import make_anime

pytestmark = pytest.mark.anyio

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
            **columns,
        )
    )
    session.flush()


def time_limit() -> timedelta:
    """How long after a prompt is served it stays open (limit plus grace)."""
    settings = get_settings()
    return timedelta(seconds=settings.answer_time_limit_seconds + settings.answer_grace_seconds)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 6, 1, 23, 59, 59, tzinfo=UTC),
        # Already 2 June in Tokyo, still 1 June in UTC.
        datetime(2026, 6, 2, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    ],
)
async def test_f030_today_is_the_current_utc_date(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, now: datetime
) -> None:
    await api_session.run_sync(make_puzzle, DAY - timedelta(days=1), 5)
    await api_session.run_sync(make_puzzle, DAY, 7)
    await api_session.run_sync(make_puzzle, DAY + timedelta(days=1), 6)
    set_now(now)

    response = await api_client.get("/api/puzzle/today")

    assert response.status_code == 200
    body = response.json()
    assert body["day"] == "2026-06-01"
    assert body["prompt_count"] == 7


async def test_f030_returns_404_when_today_has_no_puzzle(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY - timedelta(days=1))
    await api_session.run_sync(make_puzzle, DAY + timedelta(days=1))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.status_code == 404


async def test_f030_progress_is_empty_for_a_new_visitor(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.json()["progress"] == []


async def test_f030_progress_lists_finished_prompts_with_outcome_points_and_tier(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        earlier = NOON - timedelta(minutes=5)
        # Inserted out of order: progress comes back by position.
        start_prompt(session, player_id, prompts[1], earlier, outcome="expired", points=0)
        start_prompt(
            session,
            player_id,
            prompts[0],
            earlier,
            outcome="accepted",
            points=60,
            rarity_tier="niche",
        )
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.json()["progress"] == [
        {"position": 1, "outcome": "accepted", "points": 60, "rarity_tier": "niche"},
        {"position": 2, "outcome": "expired", "points": 0, "rarity_tier": None},
    ]


async def test_f030_unanswered_prompt_past_its_deadline_counts_as_expired(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        start_prompt(session, player_id, prompts[0], NOON - time_limit() - timedelta(seconds=1))
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.json()["progress"] == [
        {"position": 1, "outcome": "expired", "points": 0, "rarity_tier": None}
    ]


async def test_f030_prompt_still_inside_its_time_limit_is_not_in_progress(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        # Exactly at limit plus grace: the last moment a guess is still accepted.
        start_prompt(session, player_id, prompts[0], NOON - time_limit())
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.json()["progress"] == []


async def test_f030_progress_excludes_other_players_and_other_days(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        yesterday = DAY - timedelta(days=1)
        old_prompts = make_puzzle(session, yesterday)
        prompts = make_puzzle(session, DAY)
        player_id, other_id = make_player(session), make_player(session)
        earlier = NOON - timedelta(minutes=5)
        start_prompt(session, other_id, prompts[0], earlier, outcome="expired", points=0)
        start_prompt(
            session,
            player_id,
            old_prompts[0],
            earlier - timedelta(days=1),
            day=yesterday,
            outcome="expired",
            points=0,
        )
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.json()["progress"] == []


async def test_f030_malformed_player_cookie_is_treated_as_a_new_visitor(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    api_client.cookies.set(PLAYER_COOKIE, "not-a-uuid")
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    assert response.status_code == 200
    assert response.json()["progress"] == []


async def test_f030_response_never_contains_prompt_text_or_answers(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        start_prompt(
            session,
            player_id,
            prompts[0],
            NOON - timedelta(minutes=5),
            outcome="accepted",
            points=100,
            rarity_tier="uh-ni-me",
        )
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.get("/api/puzzle/today")

    body = response.json()
    assert set(body) == {"day", "prompt_count", "progress"}
    assert [set(entry) for entry in body["progress"]] == [
        {"position", "outcome", "points", "rarity_tier"}
    ]
    # Neither the prompt text nor the name of the answer the player matched.
    assert "Name an anime" not in response.text
    assert "Answer to" not in response.text
