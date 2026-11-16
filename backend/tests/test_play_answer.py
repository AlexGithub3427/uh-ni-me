"""POST /api/play/{day}/prompt/{n}/answer (F-032)."""

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

MAX_GUESSES = get_settings().max_guesses_per_prompt
BLEND_MIN = get_settings().scoring_blend_min_submissions
WRONG = {
    "accepted": False,
    "finished": False,
    "matched_name": None,
    "points": 0,
    "rarity_tier": None,
}
EXPIRED = WRONG | {"finished": True}


@dataclass
class Game:
    player_id: uuid.UUID
    prompt_id: int
    titan_id: int
    mob_id: int


async def new_game(
    api_client: httpx2.AsyncClient,
    api_session: AsyncSession,
    *,
    started_at: datetime | None = NOON - timedelta(seconds=5),
    guess_count: int = 0,
) -> Game:
    """A puzzle whose first prompt has two answers, and a player the client's cookie names.

    The clock is NOON. The first prompt was served at ``started_at`` (None: not served).
    """

    def seed(session: Session) -> Game:
        prompt = make_puzzle(session, DAY)[0]
        titan = add_answer(
            session,
            prompt,
            make_anime(session, "Attack on Titan", popularity=5000),
            "Shingeki no Kyojin",
            base_rarity=0.1,
        )
        mob = add_answer(
            session, prompt, make_anime(session, "Mob Psycho 100", popularity=300), base_rarity=0.9
        )
        player_id = make_player(session)
        if started_at:
            start_prompt(session, player_id, prompt, started_at, guess_count=guess_count)
        return Game(player_id, prompt.id, titan.id, mob.id)

    game = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(game.player_id))
    set_now(NOON)
    return game


async def guess(
    api_client: httpx2.AsyncClient, text: str, n: int = 1, day: object = DAY
) -> httpx2.Response:
    return await api_client.post(f"/api/play/{day}/prompt/{n}/answer", json={"text": text})


async def the_submission(api_session: AsyncSession) -> Submission:
    return (await api_session.scalars(select(Submission))).one()


async def times_answered(api_session: AsyncSession, game: Game) -> dict[int, int]:
    rows = await api_session.execute(
        select(PromptAnswer.entity_id, PromptAnswer.times_answered).where(
            PromptAnswer.prompt_id == game.prompt_id
        )
    )
    return {entity_id: count for entity_id, count in rows}


async def test_f032_a_guess_for_a_prompt_that_was_never_started_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session, started_at=None)

    response = await guess(api_client, "Attack on Titan")

    assert response.status_code == 409
    assert (await api_session.scalars(select(Submission))).all() == []
    assert await times_answered(api_session, game) == {game.titan_id: 0, game.mob_id: 0}


async def test_f032_another_players_started_prompt_does_not_count(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    other_id = await api_session.run_sync(make_player)
    api_client.cookies.set(PLAYER_COOKIE, str(other_id))

    response = await guess(api_client, "Attack on Titan")

    assert response.status_code == 409
    assert (await the_submission(api_session)).outcome is None


@pytest.mark.parametrize("text", ["", "   ", "\t\n", "a" * 201])
async def test_f032_blank_or_overlong_text_is_rejected_and_is_not_a_guess(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, text: str
) -> None:
    await new_game(api_client, api_session)

    response = await guess(api_client, text)

    assert response.status_code == 422
    row = await the_submission(api_session)
    assert (row.guess_count, row.wrong_guesses, row.outcome) == (0, [], None)


async def test_f032_a_body_without_text_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)

    response = await api_client.post(f"/api/play/{DAY}/prompt/1/answer", json={})

    assert response.status_code == 422


async def test_f032_a_wrong_guess_is_recorded_and_leaves_the_prompt_open(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)

    response = await guess(api_client, "Naruto")

    assert response.status_code == 200
    assert response.json() == WRONG
    row = await the_submission(api_session)
    assert (row.guess_count, row.wrong_guesses) == (1, ["Naruto"])
    assert (row.outcome, row.finished_at, row.matched_entity_id, row.points) == (
        None,
        None,
        None,
        None,
    )
    assert await times_answered(api_session, game) == {game.titan_id: 0, game.mob_id: 0}


async def test_f032_the_player_may_guess_again_after_a_wrong_guess(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)
    await guess(api_client, "Naruto")
    await guess(api_client, "Bleach")

    response = await guess(api_client, "Attack on Titan")

    assert response.json()["accepted"] is True
    row = await the_submission(api_session)
    assert (row.guess_count, row.wrong_guesses) == (3, ["Naruto", "Bleach"])
    assert row.outcome == "accepted"


async def test_f032_the_first_valid_guess_is_accepted_and_stored(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)

    response = await guess(api_client, " attack on titan ")

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "finished": True,
        "matched_name": "Attack on Titan",
        "points": 10,
        "rarity_tier": "larp",
    }
    row = await the_submission(api_session)
    assert (row.outcome, row.finished_at) == ("accepted", NOON)
    assert (row.raw_text, row.matched_entity_id) == ("attack on titan", game.titan_id)
    assert (row.points, row.rarity_tier) == (10, "larp")
    assert (row.guess_count, row.wrong_guesses) == (1, [])
    assert await times_answered(api_session, game) == {game.titan_id: 1, game.mob_id: 0}


async def test_f032_a_rare_answer_scores_by_its_own_rarity(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)

    body = (await guess(api_client, "Mob Psycho 100")).json()

    assert (body["points"], body["rarity_tier"]) == (100, "uh-ni-me")
    row = await the_submission(api_session)
    assert (row.points, row.rarity_tier, row.matched_entity_id) == (100, "uh-ni-me", game.mob_id)


async def test_f032_a_guess_after_an_accepted_answer_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    await guess(api_client, "Attack on Titan")

    response = await guess(api_client, "Mob Psycho 100")

    assert response.status_code == 409
    row = await the_submission(api_session)
    assert (row.matched_entity_id, row.points, row.guess_count) == (game.titan_id, 10, 1)
    assert await times_answered(api_session, game) == {game.titan_id: 1, game.mob_id: 0}


async def test_f032_a_guess_after_the_time_limit_and_grace_expires_the_prompt(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    late = time_limit() + timedelta(milliseconds=1)
    game = await new_game(api_client, api_session, started_at=NOON - late)

    response = await guess(api_client, "Attack on Titan")

    assert response.status_code == 200
    assert response.json() == EXPIRED
    row = await the_submission(api_session)
    assert (row.outcome, row.points, row.rarity_tier) == ("expired", 0, None)
    # It ran out when the grace ended, whenever the server got to write it down.
    assert row.finished_at == row.started_at + time_limit()
    assert (row.matched_entity_id, row.raw_text) == (None, None)
    assert (row.guess_count, row.wrong_guesses) == (0, [])
    assert await times_answered(api_session, game) == {game.titan_id: 0, game.mob_id: 0}


async def test_f032_a_guess_within_the_grace_period_is_still_matched(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    # Exactly at limit plus grace: past the countdown the client shows, still open here.
    await new_game(api_client, api_session, started_at=NOON - time_limit())

    response = await guess(api_client, "Attack on Titan")

    assert response.json()["accepted"] is True
    assert (await the_submission(api_session)).finished_at == NOON


async def test_f032_guessing_again_on_an_expired_prompt_changes_nothing(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session, started_at=NOON - timedelta(minutes=1))
    await guess(api_client, "Attack on Titan")
    finished_at = (await the_submission(api_session)).finished_at

    set_now(NOON + timedelta(minutes=5))
    response = await guess(api_client, "Attack on Titan")

    assert response.json() == EXPIRED
    row = await the_submission(api_session)
    assert (row.outcome, row.finished_at, row.points) == ("expired", finished_at, 0)


async def test_f032_guesses_beyond_the_maximum_are_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session, guess_count=MAX_GUESSES)

    response = await guess(api_client, "Attack on Titan")

    assert response.status_code == 429
    row = await the_submission(api_session)
    assert (row.guess_count, row.outcome, row.wrong_guesses) == (MAX_GUESSES, None, [])
    assert await times_answered(api_session, game) == {game.titan_id: 0, game.mob_id: 0}


async def test_f032_the_last_allowed_guess_is_still_matched(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session, guess_count=MAX_GUESSES - 1)

    response = await guess(api_client, "Attack on Titan")

    assert response.json()["accepted"] is True
    assert (await the_submission(api_session)).guess_count == MAX_GUESSES


async def test_f032_a_player_out_of_guesses_still_expires_at_the_deadline(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(
        api_client, api_session, started_at=NOON - timedelta(minutes=1), guess_count=MAX_GUESSES
    )

    response = await guess(api_client, "Attack on Titan")

    assert response.json() == EXPIRED


@pytest.mark.parametrize("text", ["Shingeki no Kyojin", "SHINGEKI NO KYOJIN!", "Atack on Titn"])
async def test_f032_matches_an_alias_exactly_or_by_similarity(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, text: str
) -> None:
    game = await new_game(api_client, api_session)

    body = (await guess(api_client, text)).json()

    assert (body["accepted"], body["matched_name"]) == (True, "Attack on Titan")
    row = await the_submission(api_session)
    assert (row.raw_text, row.matched_entity_id) == (text, game.titan_id)


async def test_f032_only_this_prompts_answers_are_matched(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    await new_game(api_client, api_session)

    def seed(session: Session) -> None:
        other_prompt = make_puzzle(session, DAY + timedelta(days=1))[0]
        add_answer(session, other_prompt, make_anime(session, "Naruto"))

    await api_session.run_sync(seed)

    assert (await guess(api_client, "Naruto")).json() == WRONG


async def test_f032_equally_good_matches_award_the_more_popular_answer(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    def seed(session: Session) -> tuple[uuid.UUID, int]:
        prompt = make_puzzle(session, DAY)[0]
        old = make_anime(session, "Hunter x Hunter (1999)", popularity=800, start_year=1999)
        new = make_anime(session, "Hunter x Hunter (2011)", popularity=7000, start_year=2011)
        add_answer(session, prompt, old, "Hunter x Hunter", base_rarity=0.9)
        add_answer(session, prompt, new, "Hunter x Hunter", base_rarity=0.1)
        player_id = make_player(session)
        start_prompt(session, player_id, prompt, NOON)
        return player_id, new.id

    player_id, new_id = await api_session.run_sync(seed)
    api_client.cookies.set(PLAYER_COOKIE, str(player_id))
    set_now(NOON)

    body = (await guess(api_client, "Hunter x Hunter")).json()

    assert (body["matched_name"], body["points"]) == ("Hunter x Hunter (2011)", 10)
    assert (await the_submission(api_session)).matched_entity_id == new_id


async def test_f032_points_and_tier_are_stored_at_answer_time(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    await guess(api_client, "Attack on Titan")

    # The answer becomes rare afterwards.
    await api_session.execute(
        update(PromptAnswer)
        .where(PromptAnswer.entity_id == game.titan_id)
        .values(base_rarity=0.95, times_answered=500)
    )
    today = (await api_client.get("/api/puzzle/today")).json()

    row = await the_submission(api_session)
    await api_session.refresh(row)
    assert (row.points, row.rarity_tier) == (10, "larp")
    [progress] = today["progress"]
    assert (progress["points"], progress["rarity_tier"]) == (10, "larp")


async def answered_before(api_session: AsyncSession, entity_id: int, times: int) -> None:
    """Other players already gave this answer ``times`` times."""
    await api_session.execute(
        update(PromptAnswer).where(PromptAnswer.entity_id == entity_id).values(times_answered=times)
    )


async def test_f033_an_answer_many_players_gave_scores_less_than_its_base_rarity(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    # With this guess the prompt is 500 answers past the minimum: a weight of 0.25.
    await answered_before(api_session, game.mob_id, BLEND_MIN + 499)

    body = (await guess(api_client, "Mob Psycho 100")).json()

    # Base rarity 0.9 and observed rarity 0 (the most-given answer): 0.75 * 0.9 = 0.675.
    assert (body["points"], body["rarity_tier"]) == (85, "weeb")
    row = await the_submission(api_session)
    assert (row.points, row.rarity_tier) == (85, "weeb")


async def test_f033_times_answered_is_ignored_below_the_minimum_submissions(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    await answered_before(api_session, game.mob_id, BLEND_MIN - 2)

    body = (await guess(api_client, "Mob Psycho 100")).json()

    assert (body["points"], body["rarity_tier"]) == (100, "uh-ni-me")


async def test_f033_the_blend_counts_every_answer_of_the_prompt_and_no_other(
    api_client: httpx2.AsyncClient, api_session: AsyncSession
) -> None:
    game = await new_game(api_client, api_session)
    await answered_before(api_session, game.mob_id, BLEND_MIN + 498)

    def other_prompt(session: Session) -> None:
        prompt = make_puzzle(session, DAY + timedelta(days=1))[0]
        add_answer(session, prompt, make_anime(session, "Naruto"))

    await api_session.run_sync(other_prompt)
    await api_session.execute(
        update(PromptAnswer)
        .where(PromptAnswer.prompt_id != game.prompt_id)
        .values(times_answered=10_000)
    )

    body = (await guess(api_client, "Attack on Titan")).json()

    # 1 of the prompt's 550 answers, and its most-given answer has 549: the observed
    # rarity is 1 - log(2)/log(550) = 0.89 at a weight of 0.25, so the rarity is
    # 0.75 * 0.1 + 0.25 * 0.89 = 0.30. Counting the other prompt's 10,000 would make it 0.48.
    assert (body["points"], body["rarity_tier"]) == (30, "normie")


@pytest.mark.parametrize("text", ["Attack on Titan", "Naruto"])
async def test_f032_response_never_contains_the_answer_list(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, text: str
) -> None:
    await new_game(api_client, api_session)

    response = await guess(api_client, text)

    assert set(response.json()) == {
        "accepted",
        "finished",
        "matched_name",
        "points",
        "rarity_tier",
    }
    assert "Mob Psycho" not in response.text
    assert "Shingeki" not in response.text


@pytest.mark.parametrize("offset_days", [-1, 1])
async def test_f032_a_day_other_than_today_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, offset_days: int
) -> None:
    await new_game(api_client, api_session)
    other_day = DAY + timedelta(days=offset_days)
    await api_session.run_sync(make_puzzle, other_day)

    response = await guess(api_client, "Attack on Titan", day=other_day)

    assert response.status_code == 404
    assert (await the_submission(api_session)).guess_count == 0


@pytest.mark.parametrize("n", [0, 8])
async def test_f032_a_position_outside_the_puzzle_is_not_found(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, n: int
) -> None:
    await new_game(api_client, api_session)

    response = await guess(api_client, "Attack on Titan", n=n)

    assert response.status_code == 404


@pytest.mark.parametrize("cookie", [None, "not-a-uuid", "00000000-0000-4000-8000-000000000000"])
async def test_f032_a_request_without_a_known_player_is_rejected(
    api_client: httpx2.AsyncClient, api_session: AsyncSession, cookie: str | None
) -> None:
    await new_game(api_client, api_session)
    api_client.cookies.clear()
    if cookie:
        api_client.cookies.set(PLAYER_COOKIE, cookie)

    response = await guess(api_client, "Attack on Titan")

    assert response.status_code == 401
    assert (await the_submission(api_session)).guess_count == 0
