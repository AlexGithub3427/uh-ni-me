"""Prompt generation and filtering (F-021)."""

import re
from datetime import date

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import Entity, Fact, Prompt, PromptAnswer, PromptTemplate
from app.services.prompt_templates import TEMPLATES
from jobs.generate_prompts import GenerationResult, generate_prompts, main
from jobs.seed_templates import seed_templates
from tests.factories import make_anime, make_character, make_franchise, make_studio

TODAY = date(2026, 6, 1)


@pytest.fixture
def session(db_session: Session) -> Session:
    """A session with the templates seeded."""
    seed_templates(db_session)
    return db_session


def generate(
    session: Session, *slugs: str, min_answers: int = 2, max_answers: int = 4
) -> GenerationResult:
    """Generate prompts for the named templates (all of them if none are named)."""
    templates = tuple(t for t in TEMPLATES if t.slug in slugs) if slugs else TEMPLATES
    assert len(templates) == (len(slugs) or len(TEMPLATES))
    result = generate_prompts(
        session,
        today=TODAY,
        min_answers=min_answers,
        max_answers=max_answers,
        templates=templates,
    )
    session.expire_all()
    return result


def prompts(session: Session, slug: str, *, active: bool | None = True) -> list[Prompt]:
    statement = (
        select(Prompt)
        .join(PromptTemplate, PromptTemplate.id == Prompt.template_id)
        .where(PromptTemplate.slug == slug)
        .order_by(Prompt.text)
    )
    if active is not None:
        statement = statement.where(Prompt.active == active)
    return list(session.scalars(statement))


def texts(session: Session, slug: str) -> list[str]:
    return [prompt.text for prompt in prompts(session, slug)]


def answers(session: Session, prompt: Prompt) -> dict[str, PromptAnswer]:
    """A prompt's answers by entity name."""
    rows = session.execute(
        select(Entity.canonical_name, PromptAnswer)
        .join(PromptAnswer, PromptAnswer.entity_id == Entity.id)
        .where(PromptAnswer.prompt_id == prompt.id)
    )
    return {name: answer for name, answer in rows}


def studio_with_anime(session: Session, name: str, count: int) -> Entity:
    studio = make_studio(session, name)
    for number in range(count):
        make_anime(session, f"{name} anime {number}", studios=[studio])
    return studio


# --- filtering by answer count ------------------------------------------------


def test_f021_keeps_only_prompts_whose_answer_count_is_in_range(session: Session) -> None:
    studio_with_anime(session, "Too Few", 1)
    studio_with_anime(session, "At Min", 2)
    studio_with_anime(session, "At Max", 4)
    studio_with_anime(session, "Too Many", 5)

    generate(session, "anime-by-studio", min_answers=2, max_answers=4)

    assert texts(session, "anime-by-studio") == [
        "Name an anime by At Max",
        "Name an anime by At Min",
    ]
    assert prompts(session, "anime-by-studio", active=None) == prompts(session, "anime-by-studio")


def test_f021_precomputes_every_answer_of_a_kept_prompt(session: Session) -> None:
    studio = studio_with_anime(session, "Bones", 3)
    make_anime(session, "Someone else's anime")

    generate(session, "anime-by-studio")

    (prompt,) = prompts(session, "anime-by-studio")
    assert prompt.params == {"studio": studio.id}
    assert set(answers(session, prompt)) == {"Bones anime 0", "Bones anime 1", "Bones anime 2"}


def test_f021_reports_how_many_candidates_were_tried_and_kept(session: Session) -> None:
    studio_with_anime(session, "Too Few", 1)
    studio_with_anime(session, "Kept", 2)

    result = generate(session, "anime-by-studio")

    assert result == GenerationResult(candidates=2, kept=1, deactivated=0)


def test_f021_skips_inactive_templates(session: Session) -> None:
    studio_with_anime(session, "Bones", 2)
    session.execute(
        update(PromptTemplate).where(PromptTemplate.slug == "anime-by-studio").values(active=False)
    )

    generate(session, "anime-by-studio")

    assert prompts(session, "anime-by-studio", active=None) == []


# --- base_rarity --------------------------------------------------------------


def test_f021_each_answer_gets_its_own_base_rarity_from_its_popularity(session: Session) -> None:
    studio = make_studio(session, "Bones")
    make_anime(session, "Hit", popularity=99, studios=[studio])
    make_anime(session, "Known", popularity=9, studios=[studio])
    make_anime(session, "Obscure", popularity=0, studios=[studio])

    generate(session, "anime-by-studio")

    (prompt,) = prompts(session, "anime-by-studio")
    rarity = {name: answer.base_rarity for name, answer in answers(session, prompt).items()}
    assert rarity == pytest.approx({"Hit": 0.0, "Known": 0.5, "Obscure": 1.0})


def test_f021_base_rarity_is_normalized_within_each_prompt(session: Session) -> None:
    bones = make_studio(session, "Bones")
    mappa = make_studio(session, "MAPPA")
    make_anime(session, "Shared", popularity=9, studios=[bones, mappa])
    make_anime(session, "Bones hit", popularity=99, studios=[bones])
    make_anime(session, "MAPPA obscure", popularity=0, studios=[mappa])

    generate(session, "anime-by-studio")

    by_bones, by_mappa = prompts(session, "anime-by-studio")
    # The same anime is the rarest answer for Bones and the most common for MAPPA.
    assert answers(session, by_bones)["Shared"].base_rarity == 1.0
    assert answers(session, by_mappa)["Shared"].base_rarity == 0.0


# --- regenerating -------------------------------------------------------------


def test_f021_regenerating_preserves_times_answered_and_updates_the_answers(
    session: Session,
) -> None:
    studio = make_studio(session, "Bones")
    make_anime(session, "Hit", popularity=99, studios=[studio])
    known = make_anime(session, "Known", popularity=9, studios=[studio])
    dropped = make_anime(session, "Dropped", popularity=0, studios=[studio])
    generate(session, "anime-by-studio")
    (prompt,) = prompts(session, "anime-by-studio")
    prompt_id = prompt.id
    session.execute(
        update(PromptAnswer)
        .where(PromptAnswer.prompt_id == prompt_id, PromptAnswer.entity_id == known.id)
        .values(times_answered=7)
    )

    # Upstream, one anime leaves the studio and a more popular one joins it.
    session.execute(
        delete(Fact).where(Fact.subject_id == dropped.id, Fact.predicate == "produced_by")
    )
    make_anime(session, "Newcomer", popularity=9999, studios=[studio])
    generate(session, "anime-by-studio")

    (prompt,) = prompts(session, "anime-by-studio", active=None)
    assert prompt.id == prompt_id
    regenerated = answers(session, prompt)
    assert set(regenerated) == {"Hit", "Known", "Newcomer"}
    assert regenerated["Known"].times_answered == 7
    assert regenerated["Newcomer"].times_answered == 0
    # Rarity is recomputed against the new answer set: log10(1 + popularity) is now
    # 4, 2 and 1, so "Hit" moves from 0 to (4 - 2) / (4 - 1).
    assert regenerated["Newcomer"].base_rarity == 0.0
    assert regenerated["Hit"].base_rarity == pytest.approx(2 / 3)
    assert regenerated["Known"].base_rarity == 1.0


def test_f021_a_prompt_that_leaves_the_range_is_deactivated_and_comes_back(
    session: Session,
) -> None:
    studio = make_studio(session, "Bones")
    make_anime(session, "First", studios=[studio])
    second = make_anime(session, "Second", studios=[studio])
    generate(session, "anime-by-studio")
    (prompt,) = prompts(session, "anime-by-studio")

    session.execute(delete(Fact).where(Fact.subject_id == second.id))
    result = generate(session, "anime-by-studio")

    assert result.deactivated == 1
    assert [p.id for p in prompts(session, "anime-by-studio", active=False)] == [prompt.id]
    # Its answers stay as they were, since past puzzles may still point at it.
    assert set(answers(session, prompt)) == {"First", "Second"}

    make_anime(session, "Third", studios=[studio])
    result = generate(session, "anime-by-studio")

    assert result.deactivated == 0
    (reactivated,) = prompts(session, "anime-by-studio")
    assert reactivated.id == prompt.id
    assert set(answers(session, reactivated)) == {"First", "Third"}


def test_f021_a_prompt_that_is_no_longer_a_candidate_is_deactivated(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Airing {number}", start_year=2025, end_year=None)
    generate(session, "anime-currently-airing")
    (last_year,) = prompts(session, "anime-currently-airing")

    generate_prompts(
        session,
        today=date(2027, 1, 1),
        min_answers=2,
        max_answers=4,
        templates=[t for t in TEMPLATES if t.slug == "anime-currently-airing"],
    )
    session.expire_all()

    (this_year,) = prompts(session, "anime-currently-airing")
    assert this_year.params == {"year": 2027}
    assert [p.id for p in prompts(session, "anime-currently-airing", active=False)] == [
        last_year.id
    ]


def test_f021_regenerating_leaves_other_templates_prompts_alone(session: Session) -> None:
    studio_with_anime(session, "Bones", 2)
    generate(session, "anime-by-studio", "anime-premiered-in-year")
    assert texts(session, "anime-premiered-in-year") == ["Name an anime that premiered in 2010"]

    result = generate(session, "anime-by-studio")

    assert result.deactivated == 0
    assert texts(session, "anime-premiered-in-year") == ["Name an anime that premiered in 2010"]


# --- params and prompt text ---------------------------------------------------


def test_f021_fixed_choices_each_become_a_candidate(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Panned {number}", score=50)
    make_anime(session, "Middling", score=62)

    generate(session, "anime-rated-below")

    below_60, below_65 = prompts(session, "anime-rated-below")
    assert (below_60.text, below_60.params) == (
        "Name an anime rated below 60",
        {"score": 60, "max": 59},
    )
    assert (below_65.text, below_65.params) == (
        "Name an anime rated below 65",
        {"score": 65, "max": 64},
    )
    assert set(answers(session, below_65)) == {"Panned 0", "Panned 1", "Middling"}


def test_f021_year_prompts_cover_each_year_up_to_this_year(session: Session) -> None:
    for year in (2024, 2026, 2027):
        for number in range(2):
            make_anime(session, f"{year} anime {number}", start_year=year)

    generate(session, "anime-premiered-in-year")

    # 2025 has no anime, and 2027 has not happened yet.
    assert texts(session, "anime-premiered-in-year") == [
        "Name an anime that premiered in 2024",
        "Name an anime that premiered in 2026",
    ]


def test_f021_currently_airing_uses_the_year_of_generation(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Airing {number}", start_year=2025, end_year=None)
    make_anime(session, "Not started", start_year=2027, end_year=None)
    make_anime(session, "Finished", start_year=2025)

    generate(session, "anime-currently-airing")

    (prompt,) = prompts(session, "anime-currently-airing")
    assert (prompt.text, prompt.params) == ("Name an anime currently airing", {"year": 2026})
    assert set(answers(session, prompt)) == {"Airing 0", "Airing 1"}


def test_f021_decade_prompts_carry_the_decade_and_its_range(session: Session) -> None:
    studio = make_studio(session, "Bones")
    for number in range(2):
        make_anime(session, f"Old {number}", start_year=1998, end_year=2001, studios=[studio])

    generate(session, "anime-by-studio-in-decade")

    nineties, noughties = prompts(session, "anime-by-studio-in-decade")
    assert (nineties.text, nineties.params) == (
        "Name an anime by Bones from the 1990s",
        {"studio": studio.id, "decade": 1990, "from": 1990, "to": 1999},
    )
    assert noughties.text == "Name an anime by Bones from the 2000s"


def test_f021_genre_prompts_use_an_before_a_vowel(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Anime {number}", genres=["Action", "Comedy"])

    generate(session, "anime-by-genre")

    assert texts(session, "anime-by-genre") == ["Name a Comedy anime", "Name an Action anime"]


def test_f021_no_template_puts_an_article_before_an_entity_name() -> None:
    # "a"/"an" goes by the first letter, which is wrong for names such as
    # "ufotable" and "8bit", so templates are worded to avoid needing it.
    article_before_name = re.compile(r"\ban? \{(studio|anime|franchise)\}", re.IGNORECASE)

    assert [t.slug for t in TEMPLATES if article_before_name.search(t.text)] == []


def test_f021_studio_character_prompt_names_the_studio_without_an_article(
    session: Session,
) -> None:
    studio = make_studio(session, "ufotable")
    anime = make_anime(session, "Fate/Zero", studios=[studio])
    for number in range(2):
        make_character(session, f"Character {number}", appears_in=[anime])

    generate(session, "character-from-studio-anime")

    assert texts(session, "character-from-studio-anime") == [
        "Name a character from an anime by ufotable"
    ]


def test_f021_two_genre_prompts_take_each_pair_once(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Anime {number}", genres=["Comedy", "Action", "Drama"])

    result = generate(session, "anime-by-two-genres")

    assert result.candidates == 3
    assert texts(session, "anime-by-two-genres") == [
        "Name a Comedy and Drama anime",
        "Name an Action and Comedy anime",
        "Name an Action and Drama anime",
    ]
    assert prompts(session, "anime-by-two-genres")[1].params == {
        "genre": "Action",
        "genre2": "Comedy",
    }


def test_f021_tag_prompts_come_from_the_tags_in_the_data(session: Session) -> None:
    for number in range(2):
        make_anime(session, f"Anime {number}", tags=["Time Travel"])

    generate(session, "anime-by-tag")

    assert texts(session, "anime-by-tag") == ["Name a Time Travel anime"]


def test_f021_entity_params_hold_the_id_and_the_text_shows_the_name(session: Session) -> None:
    franchise = make_franchise(session, "Naruto")
    first = make_anime(session, "Naruto", franchise=franchise)
    second = make_anime(session, "Naruto: Shippuden", franchise=franchise)
    make_character(session, "Naruto Uzumaki", appears_in=[first, second])
    make_character(session, "Sai", appears_in=[second])

    generate(session, "character-from-franchise", "character-from-anime")

    (by_franchise,) = prompts(session, "character-from-franchise")
    assert by_franchise.text == "Name a character from the Naruto franchise"
    assert by_franchise.params == {"franchise": franchise.id}
    (by_anime,) = prompts(session, "character-from-anime")
    assert by_anime.text == "Name a character from Naruto: Shippuden"
    assert by_anime.params == {"anime": second.id}


def test_f021_every_seeded_template_generates_prompts(session: Session) -> None:
    studio = make_studio(session, "Bones")
    franchise = make_franchise(session, "Franchise")
    anime = [
        make_anime(
            session,
            f"Anime {number}",
            start_year=2020,
            end_year=None,
            score=90,
            episodes=300,
            franchise=franchise,
            studios=[studio],
            genres=["Action", "Comedy"],
            tags=["Isekai"],
            source_material="MANGA",
        )
        for number in range(3)
    ]
    for number in range(3):
        make_anime(
            session,
            f"Movie {number}",
            start_year=2020,
            score=40,
            episodes=1,
            franchise=franchise,
            format="MOVIE",
            studios=[studio],
            genres=["Action"],
            source_material="ORIGINAL",
        )
    for number in range(3):
        make_anime(session, f"Short {number}", start_year=2020, episodes=12)
    for number in range(3):
        make_franchise(session, f"Movie franchise {number}")
    for number in range(3):
        make_character(session, f"Character {number}", appears_in=anime)

    generate(session, min_answers=1, max_answers=1000)

    without_prompts = [t.slug for t in TEMPLATES if not prompts(session, t.slug)]
    # Only one franchise has members here, so it is the only franchise answer; every
    # template still produces at least one prompt.
    assert without_prompts == []
    assert not [p.text for t in TEMPLATES for p in prompts(session, t.slug) if "{" in p.text]


# --- CLI ----------------------------------------------------------------------


def test_f021_cli_generates_with_the_configured_range(
    session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    studio_with_anime(session, "Below Default Min", 24)
    studio_with_anime(session, "At Default Min", 25)

    assert main([], session=session, today=TODAY) == 0

    session.expire_all()
    assert texts(session, "anime-by-studio") == ["Name an anime by At Default Min"]
    assert "prompts kept" in capsys.readouterr().out
