"""Anonymous players: the ``player_id`` cookie (F-034)."""

import uuid

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PLAYER_COOKIE
from app.models import Player, Submission
from tests.game_helpers import DAY, NOON, make_player, make_puzzle, set_now

pytestmark = pytest.mark.anyio

START_1 = f"/api/play/{DAY}/prompt/1/start"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


async def player_ids(api_session: AsyncSession) -> list[uuid.UUID]:
    return list(await api_session.scalars(select(Player.id)))


async def test_f034_a_request_without_the_cookie_creates_a_player_and_sets_the_cookie(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    set_now(NOON)

    response = await api_client.post(START_1)

    assert response.status_code == 200
    [player_id] = await player_ids(api_session)
    assert response.cookies[PLAYER_COOKIE] == str(player_id)
    [submission] = await api_session.scalars(select(Submission))
    assert submission.player_id == player_id


async def test_f034_the_cookie_is_httponly_samesite_lax_and_persistent(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    set_now(NOON)

    response = await api_client.post(START_1)

    attributes = {part.strip().lower() for part in response.headers["set-cookie"].split(";")}
    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert "path=/" in attributes
    # Without Max-Age the player would be lost when the browser closes.
    assert any(part.startswith("max-age=") for part in attributes)


async def test_f034_a_request_with_a_valid_cookie_reuses_the_existing_player(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    player_id = await api_session.run_sync(make_player)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    response = await api_client.post(START_1)

    assert response.status_code == 200
    assert await player_ids(api_session) == [player_id]
    assert "set-cookie" not in response.headers
    [submission] = await api_session.scalars(select(Submission))
    assert submission.player_id == player_id


async def test_f034_the_cookie_set_on_the_first_request_is_reused_on_the_next(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    set_now(NOON)

    await api_client.post(START_1)
    response = await api_client.post(START_1)

    assert response.status_code == 200
    assert len(await player_ids(api_session)) == 1
    assert len(list(await api_session.scalars(select(Submission)))) == 1


@pytest.mark.parametrize("cookie", ["not-a-uuid", "", UNKNOWN_ID])
async def test_f034_an_unknown_or_malformed_cookie_is_replaced_with_a_new_player(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, cookie: str
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    api_client.cookies.set(PLAYER_COOKIE, cookie)
    set_now(NOON)

    response = await api_client.post(START_1)

    assert response.status_code == 200
    [player_id] = await player_ids(api_session)
    assert str(player_id) != cookie
    assert response.cookies[PLAYER_COOKIE] == str(player_id)


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("/api/play/2026-05-31/prompt/1/start", 404),
        (f"/api/play/{DAY}/prompt/8/start", 404),
        # Prompt 1 was never played, so there is nothing to give a new player here.
        (f"/api/play/{DAY}/prompt/2/start", 409),
    ],
)
async def test_f034_a_rejected_request_creates_no_player_and_sets_no_cookie(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, url: str, status: int
) -> None:
    await api_session.run_sync(make_puzzle, DAY)
    set_now(NOON)

    response = await api_client.post(url)

    assert response.status_code == status
    assert await player_ids(api_session) == []
    assert "set-cookie" not in response.headers
