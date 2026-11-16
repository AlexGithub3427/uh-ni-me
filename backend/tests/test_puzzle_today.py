"""GET /api/puzzle/today (F-030)."""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import PLAYER_COOKIE
from tests.game_helpers import (
    DAY,
    NOON,
    make_player,
    make_puzzle,
    set_now,
    start_prompt,
    time_limit,
)

pytestmark = pytest.mark.anyio


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
