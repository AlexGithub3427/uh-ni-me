"""POST /api/play/{day}/prompt/{n}/start (F-031)."""

import uuid
from datetime import datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import PLAYER_COOKIE
from app.config import get_settings
from app.models import PromptAnswer, Submission
from tests.factories import make_anime
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


def start_url(n: int, day: object = DAY) -> str:
    return f"/api/play/{day}/prompt/{n}/start"


async def new_player(api_client: httpx2.AsyncClient, api_session: AsyncSession) -> uuid.UUID:
    """A puzzle for DAY and a player whose cookie the client sends."""

    def seed(session: Session) -> uuid.UUID:
        make_puzzle(session, DAY)
        return make_player(session)

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    return player_id


async def submissions(api_session: AsyncSession) -> list[Submission]:
    return list(await api_session.scalars(select(Submission)))


async def test_f031_start_returns_the_prompt_text_and_creates_the_submission(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    player_id = await new_player(api_client, api_session)
    set_now(NOON)

    response = await api_client.post(start_url(1))

    assert response.status_code == 200
    body = response.json()
    assert body["position"] == 1
    assert body["text"] == "Name an anime by studio 0"
    [row] = await submissions(api_session)
    assert (row.player_id, row.day, row.started_at) == (player_id, DAY, NOON)
    assert row.outcome is None
    assert row.guess_count == 0


async def test_f031_response_has_started_at_and_deadline_in_server_time(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_player(api_client, api_session)
    set_now(NOON)

    body = (await api_client.post(start_url(1))).json()

    limit = timedelta(seconds=get_settings().answer_time_limit_seconds)
    assert datetime.fromisoformat(body["started_at"]) == NOON
    assert datetime.fromisoformat(body["deadline"]) == NOON + limit


async def test_f031_prompt_n_is_rejected_until_the_previous_prompt_is_started(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_player(api_client, api_session)
    set_now(NOON)

    response = await api_client.post(start_url(2))

    assert response.status_code == 409
    assert "Name an anime" not in response.text
    assert await submissions(api_session) == []


async def test_f031_prompt_n_is_rejected_while_the_previous_prompt_is_still_open(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        # Exactly at limit plus grace: a guess would still be accepted.
        start_prompt(session, player_id, prompts[0], NOON - time_limit())
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(2))

    assert response.status_code == 409
    assert len(await submissions(api_session)) == 1


@pytest.mark.parametrize("outcome", ["accepted", "expired"])
async def test_f031_prompt_n_is_served_once_the_previous_prompt_has_an_outcome(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, outcome: str
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        # Finished a second ago, long before its deadline.
        start_prompt(session, player_id, prompts[0], NOON - timedelta(seconds=11), outcome=outcome)
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(2))

    assert response.status_code == 200
    assert response.json()["text"] == "Name an anime by studio 1"


async def test_f031_prompt_n_is_served_once_the_previous_prompt_ran_out_of_time(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id = make_player(session)
        # Unanswered, and no outcome written yet.
        start_prompt(session, player_id, prompts[0], NOON - time_limit() - timedelta(seconds=1))
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(2))

    assert response.status_code == 200
    assert response.json()["position"] == 2


async def test_f031_another_players_progress_does_not_unlock_a_prompt(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        player_id, other_id = make_player(session), make_player(session)
        start_prompt(session, other_id, prompts[0], NOON - timedelta(minutes=5), outcome="expired")
        return player_id

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(2))

    assert response.status_code == 409


@pytest.mark.parametrize("offset_days", [-1, 1])
async def test_f031_a_day_other_than_today_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, offset_days: int
) -> None:
    other_day = DAY + timedelta(days=offset_days)

    def seed(session: Session) -> uuid.UUID:
        make_puzzle(session, DAY)
        make_puzzle(session, other_day)
        return make_player(session)

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(1, other_day))

    assert response.status_code == 404
    assert "Name an anime" not in response.text
    assert await submissions(api_session) == []


async def test_f031_today_is_the_utc_date_not_the_local_one(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_player(api_client, api_session)
    # One second before the rollover.
    set_now(datetime.combine(DAY, datetime.max.time(), NOON.tzinfo).replace(microsecond=0))

    assert (await api_client.post(start_url(1))).status_code == 200
    assert (await api_client.post(start_url(1, DAY + timedelta(days=1)))).status_code == 404


async def test_f031_starting_again_returns_the_original_start_time(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_player(api_client, api_session)
    set_now(NOON)
    first = (await api_client.post(start_url(1))).json()

    set_now(NOON + timedelta(seconds=10))
    response = await api_client.post(start_url(1))

    assert response.status_code == 200
    assert response.json() == first
    [row] = await submissions(api_session)
    assert row.started_at == NOON


async def test_f031_starting_again_after_the_deadline_does_not_reopen_the_prompt(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_player(api_client, api_session)
    set_now(NOON)
    first = (await api_client.post(start_url(1))).json()

    set_now(NOON + timedelta(minutes=5))
    response = await api_client.post(start_url(1))

    assert response.json() == first
    [row] = await submissions(api_session)
    assert row.started_at == NOON


async def test_f031_response_never_contains_answers(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> uuid.UUID:
        prompts = make_puzzle(session, DAY)
        answer = make_anime(session, "Secret Answer")
        session.add(PromptAnswer(prompt_id=prompts[0].id, entity_id=answer.id, base_rarity=0.5))
        session.flush()
        return make_player(session)

    player_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(1))

    assert set(response.json()) == {"position", "text", "started_at", "deadline"}
    assert "Secret Answer" not in response.text


@pytest.mark.parametrize("n", [0, 8])
async def test_f031_a_position_outside_the_puzzle_is_not_found(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, n: int
) -> None:
    await new_player(api_client, api_session)
    set_now(NOON)

    response = await api_client.post(start_url(n))

    assert response.status_code == 404
    assert await submissions(api_session) == []


async def test_f031_returns_404_when_today_has_no_puzzle(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    player_id = await api_session.run_sync(make_player)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(start_url(1))

    assert response.status_code == 404


@pytest.mark.parametrize("cookie", [None, "not-a-uuid", "00000000-0000-4000-8000-000000000000"])
async def test_f031_a_request_without_a_known_player_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, cookie: str | None
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    if cookie:
        api_client.cookies.set(PLAYER_COOKIE, cookie)
    set_now(NOON)

    response = await api_client.post(start_url(1))

    assert response.status_code == 401
    assert "Name an anime" not in response.text
    assert await submissions(api_session) == []
