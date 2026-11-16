"""GET /api/play/{day}/prompt/{n}/result (F-035)."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import PLAYER_COOKIE
from app.config import get_settings
from app.models import PromptAnswer, Submission
from tests.factories import make_anime
from tests.game_helpers import (
    DAY,
    NOON,
    add_answer,
    make_player,
    make_puzzle,
    set_now,
    start_prompt,
    time_limit,
)

pytestmark = pytest.mark.anyio

BLEND_MIN = get_settings().scoring_blend_min_submissions
STARTED = NOON - timedelta(seconds=5)


@dataclass
class Game:
    player_id: uuid.UUID
    prompt_id: int
    mob_id: int


async def new_game(
    api_client: httpx2.AsyncClient,
    api_session: AsyncSession,
    *,
    started_at: datetime | None = STARTED,
) -> Game:
    """A puzzle whose first prompt has three answers, and a player the client's cookie names.

    The clock is NOON. The first prompt was served at ``started_at`` (None: not served).
    """

    def seed(session: Session) -> Game:
        prompt = make_puzzle(session, DAY)[0]
        # Seeded out of alphabetical order, with a lowercase name among them.
        mob = add_answer(
            session, prompt, make_anime(session, "Mob Psycho 100", popularity=300), base_rarity=0.9
        )
        add_answer(
            session, prompt, make_anime(session, "xxxHOLiC", popularity=900), base_rarity=0.5
        )
        add_answer(
            session,
            prompt,
            make_anime(session, "Attack on Titan", popularity=5000),
            "Shingeki no Kyojin",
            base_rarity=0.1,
        )
        player_id = make_player(session)
        if started_at:
            start_prompt(session, player_id, prompt, started_at)
        return Game(player_id, prompt.id, mob.id)

    game = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(game.player_id))
    set_now(NOON)
    return game


async def guess(api_client: httpx2.AsyncClient, text: str) -> httpx2.Response:
    return await api_client.post(f"/api/play/{DAY}/prompt/1/answer", json={"text": text})


async def result(api_client: httpx2.AsyncClient, n: int = 1, day: object = DAY) -> httpx2.Response:
    return await api_client.get(f"/api/play/{day}/prompt/{n}/result")


async def the_submission(api_session: AsyncSession) -> Submission:
    return (await api_session.scalars(select(Submission))).one()


async def test_f035_the_result_of_a_prompt_still_being_played_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    await guess(api_client, "Naruto")  # a wrong guess does not finish the prompt

    response = await result(api_client)

    assert response.status_code == 409
    assert "answers" not in response.json()


async def test_f035_the_result_of_a_prompt_that_was_never_started_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session, started_at=None)

    response = await result(api_client)

    assert response.status_code == 409
    assert "answers" not in response.json()


async def test_f035_a_prompt_another_player_finished_is_still_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    assert (await guess(api_client, "Attack on Titan")).json()["accepted"]
    other = await api_session.run_sync(make_player)
    api_client.cookies.set(PLAYER_COOKIE, str(other))

    response = await result(api_client)

    assert response.status_code == 409


@pytest.mark.parametrize("cookie", [None, "not-a-uuid", str(uuid.uuid4())])
async def test_f035_a_visitor_without_a_known_player_gets_no_result(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, cookie: str | None
) -> None:
    await new_game(api_client, api_session)
    api_client.cookies.clear()
    if cookie:
        api_client.cookies.set(PLAYER_COOKIE, cookie)

    response = await result(api_client)

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    ("day", "n"), [(DAY - timedelta(days=1), 1), (DAY + timedelta(days=1), 1), (DAY, 0), (DAY, 8)]
)
async def test_f035_another_day_or_a_position_outside_the_puzzle_is_not_found(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, day: object, n: int
) -> None:
    await new_game(api_client, api_session)

    response = await result(api_client, n, day)

    assert response.status_code == 404


async def test_f035_an_accepted_answer_is_reported_with_its_name_points_and_tier(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    assert (await guess(api_client, "shingeki no kyojin")).json()["accepted"]

    response = await result(api_client)

    assert response.status_code == 200
    body = response.json()
    del body["answers"]
    assert body == {
        "outcome": "accepted",
        "matched_name": "Attack on Titan",
        "points": 10,
        "rarity_tier": "larp",
    }


async def test_f035_an_expired_prompt_is_reported_with_no_answer_and_no_points(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    set_now(STARTED + time_limit() + timedelta(seconds=1))
    assert (await guess(api_client, "Attack on Titan")).json()["finished"]  # too late

    response = await result(api_client)

    assert response.status_code == 200
    body = response.json()
    del body["answers"]
    assert body == {"outcome": "expired", "matched_name": None, "points": 0, "rarity_tier": None}


async def test_f035_the_players_tier_is_the_one_stored_when_they_answered(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    assert (await guess(api_client, "Mob Psycho 100")).json()["rarity_tier"] == "uh-ni-me"
    await make_mob_the_common_answer(api_session, game)

    body = (await result(api_client)).json()

    assert (body["points"], body["rarity_tier"]) == (100, "uh-ni-me")


async def make_mob_the_common_answer(api_session: AsyncSession, game: Game) -> None:
    """So many players answer Mob Psycho 100 that it drops from ``uh-ni-me`` to ``niche``.

    With 9,500 answers past the blend minimum the observed rarity weighs 0.475, so
    Mob's rarity is 0.525 * 0.9 = 0.47 and that of an answer nobody gave rises by 0.475.
    """
    await api_session.execute(
        update(PromptAnswer)
        .where(PromptAnswer.prompt_id == game.prompt_id, PromptAnswer.entity_id == game.mob_id)
        .values(times_answered=BLEND_MIN + 9500)
    )


async def test_f035_every_valid_answer_is_listed_alphabetically_with_its_tier(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    assert (await guess(api_client, "Attack on Titan")).json()["accepted"]

    response = await result(api_client)

    # By name, ignoring case; an alias ("Shingeki no Kyojin") is not a separate answer.
    assert response.json()["answers"] == [
        {"name": "Attack on Titan", "rarity_tier": "larp"},
        {"name": "Mob Psycho 100", "rarity_tier": "uh-ni-me"},
        {"name": "xxxHOLiC", "rarity_tier": "niche"},
    ]


async def test_f035_an_expired_prompt_lists_the_answers_too(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    set_now(STARTED + time_limit() + timedelta(seconds=1))

    response = await result(api_client)

    assert [answer["name"] for answer in response.json()["answers"]] == [
        "Attack on Titan",
        "Mob Psycho 100",
        "xxxHOLiC",
    ]


async def test_f035_only_the_prompts_own_answers_are_listed(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)

    def seed_another_prompt(session: Session) -> None:
        other = make_puzzle(session, DAY + timedelta(days=1))[0]
        add_answer(session, other, make_anime(session, "Bleach"))
        make_anime(session, "Naruto")  # an answer to nothing

    await api_session.run_sync(seed_another_prompt)
    assert (await guess(api_client, "Attack on Titan")).json()["accepted"]

    names = [answer["name"] for answer in (await result(api_client)).json()["answers"]]

    assert names == ["Attack on Titan", "Mob Psycho 100", "xxxHOLiC"]


async def test_f035_the_listed_tiers_are_the_current_ones(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    assert (await guess(api_client, "Mob Psycho 100")).json()["accepted"]
    await make_mob_the_common_answer(api_session, game)

    response = await result(api_client)

    assert response.json()["answers"] == [
        {"name": "Attack on Titan", "rarity_tier": "niche"},  # 0.525 * 0.1 + 0.475 = 0.53
        {"name": "Mob Psycho 100", "rarity_tier": "niche"},  # 0.525 * 0.9 = 0.47
        {"name": "xxxHOLiC", "rarity_tier": "weeb"},  # 0.525 * 0.5 + 0.475 = 0.74
    ]


async def test_f035_a_prompt_that_ran_out_of_time_is_written_as_expired(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    await guess(api_client, "Naruto")
    set_now(STARTED + time_limit() + timedelta(minutes=3))

    response = await result(api_client)

    assert response.status_code == 200
    assert response.json()["outcome"] == "expired"
    row = await the_submission(api_session)
    await api_session.refresh(row)
    assert (row.outcome, row.points, row.rarity_tier) == ("expired", 0, None)
    # When the time ran out, not when the result was asked for.
    assert row.finished_at == STARTED + time_limit()
    assert (row.guess_count, row.wrong_guesses) == (1, ["Naruto"])


async def test_f035_reading_a_result_again_changes_nothing(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    assert (await guess(api_client, "Mob Psycho 100")).json()["accepted"]
    first = await result(api_client)
    set_now(STARTED + time_limit() + timedelta(minutes=3))

    second = await result(api_client)

    assert second.json() == first.json()
    row = await the_submission(api_session)
    await api_session.refresh(row)
    assert (row.outcome, row.finished_at, row.points) == ("accepted", NOON, 100)
    counts = await api_session.scalars(
        select(PromptAnswer.times_answered).where(PromptAnswer.entity_id == row.matched_entity_id)
    )
    assert counts.all() == [1]
