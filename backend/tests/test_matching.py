"""Matching a guess against one prompt's answer set (F-032)."""

from collections.abc import Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Prompt
from app.services.matching import match_answer
from tests.factories import make_anime, make_franchise
from tests.game_helpers import DAY, add_answer, make_puzzle

pytestmark = pytest.mark.anyio

THRESHOLD = get_settings().match_similarity_threshold


async def seed_prompt(api_session: AsyncSession, seed: Callable[[Session, Prompt], None]) -> int:
    """A prompt whose answers ``seed`` adds. Returns its id."""

    def run(session: Session) -> int:
        prompt = make_puzzle(session, DAY, size=1)[0]
        seed(session, prompt)
        return prompt.id

    return await api_session.run_sync(run)


def titan_and_mob(session: Session, prompt: Prompt) -> None:
    add_answer(session, prompt, make_anime(session, "Attack on Titan"), "Shingeki no Kyojin")
    add_answer(session, prompt, make_anime(session, "Mob Psycho 100"))
    add_answer(session, prompt, make_anime(session, "Yuu Yuu Hakusho"), "Yū Yū Hakusho")


async def matched_name(
    api_session: AsyncSession, prompt_id: int, text: str, threshold: float = THRESHOLD
) -> str | None:
    entity = await match_answer(api_session, prompt_id, text, threshold=threshold)
    return entity.canonical_name if entity else None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Attack on Titan", "Attack on Titan"),
        # romaji vs English: both are aliases of the same anime
        ("Shingeki no Kyojin", "Attack on Titan"),
        ("  shingeki no kyojin!! ", "Attack on Titan"),
        ("ATTACK ON TITAN", "Attack on Titan"),
        ("mob psycho 100", "Mob Psycho 100"),
        # long vowels fold the same way however they are typed
        ("Yu Yu Hakusho", "Yuu Yuu Hakusho"),
    ],
)
async def test_f032_matches_an_exact_alias_after_normalization(
    api_session: AsyncSession, text: str, expected: str
) -> None:
    prompt_id = await seed_prompt(api_session, titan_and_mob)

    assert await matched_name(api_session, prompt_id, text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Atack on Titn", "Attack on Titan"),
        ("Shingeki no Kyoujin", "Attack on Titan"),
        ("Mob Psyco 100", "Mob Psycho 100"),
        ("Yu Yu Hakusyo", "Yuu Yuu Hakusho"),
    ],
)
async def test_f032_matches_a_typo_by_trigram_similarity(
    api_session: AsyncSession, text: str, expected: str
) -> None:
    prompt_id = await seed_prompt(api_session, titan_and_mob)

    assert await matched_name(api_session, prompt_id, text) == expected


@pytest.mark.parametrize("text", ["Naruto", "Titan", "One Punch Man", "!!!", "100"])
async def test_f032_a_guess_that_resembles_no_answer_does_not_match(
    api_session: AsyncSession, text: str
) -> None:
    prompt_id = await seed_prompt(api_session, titan_and_mob)

    assert await matched_name(api_session, prompt_id, text) is None


async def test_f032_only_the_prompts_own_answers_can_match(api_session: AsyncSession) -> None:
    def seed(session: Session) -> tuple[int, int]:
        by_wit, by_bones = make_puzzle(session, DAY, size=2)
        add_answer(session, by_wit, make_anime(session, "Attack on Titan"))
        add_answer(session, by_bones, make_anime(session, "Mob Psycho 100"))
        return by_wit.id, by_bones.id

    by_wit, by_bones = await api_session.run_sync(seed)

    assert await matched_name(api_session, by_wit, "Mob Psycho 100") is None
    assert await matched_name(api_session, by_wit, "Mob Psyco 100") is None
    assert await matched_name(api_session, by_bones, "Mob Psycho 100") == "Mob Psycho 100"


async def test_f032_similarity_must_be_above_the_threshold(api_session: AsyncSession) -> None:
    # similarity("shingekinokyojin", "shingekinobahamut") is exactly 0.4
    def seed(session: Session, prompt: Prompt) -> None:
        add_answer(session, prompt, make_anime(session, "Shingeki no Bahamut"))

    prompt_id = await seed_prompt(api_session, seed)

    assert await matched_name(api_session, prompt_id, "Shingeki no Kyojin", 0.4) is None
    assert (
        await matched_name(api_session, prompt_id, "Shingeki no Kyojin", 0.39)
        == "Shingeki no Bahamut"
    )


async def test_f032_the_default_threshold_keeps_similar_titles_apart(
    api_session: AsyncSession,
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        add_answer(session, prompt, make_anime(session, "Shingeki no Bahamut"))
        add_answer(session, prompt, make_anime(session, "Death Parade"))
        add_answer(session, prompt, make_anime(session, "One Punch Man"))

    prompt_id = await seed_prompt(api_session, seed)

    for text in ("Shingeki no Kyojin", "Death Note", "One Piece"):
        assert await matched_name(api_session, prompt_id, text) is None


async def test_f032_an_exact_alias_beats_a_more_popular_similar_answer(
    api_session: AsyncSession,
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        add_answer(session, prompt, make_anime(session, "Attack on Titan", popularity=100))
        add_answer(
            session, prompt, make_anime(session, "Attack on Titan Season 2", popularity=9000)
        )

    prompt_id = await seed_prompt(api_session, seed)

    assert await matched_name(api_session, prompt_id, "Attack on Titan") == "Attack on Titan"
    assert (
        await matched_name(api_session, prompt_id, "attack on titan season 2")
        == "Attack on Titan Season 2"
    )


async def test_f032_the_closest_similar_answer_beats_a_more_popular_one(
    api_session: AsyncSession,
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        add_answer(session, prompt, make_anime(session, "Attack on Titan", popularity=9000))
        add_answer(session, prompt, make_anime(session, "Attack on Titan Season 2", popularity=100))

    prompt_id = await seed_prompt(api_session, seed)

    assert (
        await matched_name(api_session, prompt_id, "Atack on Titan Seasn 2")
        == "Attack on Titan Season 2"
    )


async def test_f032_a_sequel_matches_its_own_title_when_the_first_season_is_not_an_answer(
    api_session: AsyncSession,
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        add_answer(session, prompt, make_anime(session, "Attack on Titan Season 2"))

    prompt_id = await seed_prompt(api_session, seed)

    assert (
        await matched_name(api_session, prompt_id, "Attack on Titan 2")
        == "Attack on Titan Season 2"
    )


@pytest.mark.parametrize("text", ["Hunter x Hunter", "HUNTER×HUNTER", "Hunter x Huntr"])
async def test_f032_equally_good_matches_go_to_the_more_popular_answer(
    api_session: AsyncSession, text: str
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        old = make_anime(session, "Hunter x Hunter (1999)", popularity=800, start_year=1999)
        new = make_anime(session, "Hunter x Hunter (2011)", popularity=7000, start_year=2011)
        add_answer(session, prompt, old, "Hunter x Hunter")
        add_answer(session, prompt, new, "Hunter x Hunter")

    prompt_id = await seed_prompt(api_session, seed)

    assert await matched_name(api_session, prompt_id, text) == "Hunter x Hunter (2011)"


async def test_f032_a_franchise_answer_matches_through_the_franchises_aliases(
    api_session: AsyncSession,
) -> None:
    def seed(session: Session, prompt: Prompt) -> None:
        # A franchise entity carries the aliases of all its member anime (F-011).
        franchise = make_franchise(session, "Attack on Titan")
        add_answer(session, prompt, franchise, "Shingeki no Kyojin", "Attack on Titan Season 2")

    prompt_id = await seed_prompt(api_session, seed)

    for text in ("Shingeki no Kyojin", "Attack on Titan Season 2", "attack on titan"):
        assert await matched_name(api_session, prompt_id, text) == "Attack on Titan"
