"""F-020: the seeded prompt templates, each run against one small knowledge graph."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ENTITY_KINDS, Entity, PromptTemplate
from app.services.prompt_templates import TEMPLATES, TemplateDef
from jobs import seed_templates
from tests.factories import make_anime, make_character, make_franchise, make_studio

BY_SLUG = {template.slug: template for template in TEMPLATES}

FRANCHISE_SLUGS = {
    "franchise-with-movie",
    "franchise-by-studio",
    "franchise-aired-in-decade",
    "franchise-with-min-anime",
}
CHARACTER_SLUGS = {
    "character-from-anime",
    "character-from-franchise",
    "character-from-studio-anime",
    "character-from-anime-aired-in-year",
    "character-top-favourited",
}

World = dict[str, Entity]


@pytest.fixture
def world(db_session: Session) -> World:
    """Nine anime, three franchises, two studios and five characters."""
    s = db_session
    w: World = {}
    w["bones"] = make_studio(s, "Bones")
    w["madhouse"] = make_studio(s, "Madhouse")
    w["fma_franchise"] = make_franchise(s, "Fullmetal Alchemist")
    w["hxh_franchise"] = make_franchise(s, "Hunter x Hunter")
    w["one_piece_franchise"] = make_franchise(s, "One Piece")

    w["fma"] = make_anime(
        s,
        "Fullmetal Alchemist",
        popularity=500,
        start_year=2003,
        end_year=2004,
        score=79,
        episodes=51,
        franchise=w["fma_franchise"],
        studios=[w["bones"]],
        genres=["Action", "Adventure"],
        tags=["Military"],
        source_material="MANGA",
    )
    w["fmab"] = make_anime(
        s,
        "Fullmetal Alchemist: Brotherhood",
        popularity=900,
        start_year=2009,
        end_year=2010,
        score=90,
        episodes=64,
        franchise=w["fma_franchise"],
        studios=[w["bones"]],
        genres=["Action", "Adventure"],
        tags=["Military"],
        source_material="MANGA",
    )
    w["shamballa"] = make_anime(
        s,
        "Fullmetal Alchemist: The Conqueror of Shamballa",
        popularity=200,
        start_year=2005,
        score=75,
        episodes=1,
        franchise=w["fma_franchise"],
        format="MOVIE",
        studios=[w["bones"]],
        genres=["Action"],
        source_material="ORIGINAL",
    )
    w["hxh_1999"] = make_anime(
        s,
        "Hunter x Hunter (1999)",
        popularity=300,
        start_year=1999,
        end_year=2001,
        score=82,
        episodes=62,
        franchise=w["hxh_franchise"],
        genres=["Adventure"],
        source_material="MANGA",
    )
    w["hxh_2011"] = make_anime(
        s,
        "Hunter x Hunter (2011)",
        popularity=800,
        start_year=2011,
        end_year=2014,
        score=89,
        episodes=148,
        franchise=w["hxh_franchise"],
        studios=[w["madhouse"]],
        genres=["Action", "Adventure"],
        source_material="MANGA",
    )
    w["one_piece"] = make_anime(
        s,
        "One Piece",
        popularity=1000,
        start_year=1999,
        end_year=None,
        score=87,
        franchise=w["one_piece_franchise"],
        genres=["Adventure"],
        tags=["Pirates"],
        source_material="MANGA",
    )
    w["perfect_blue"] = make_anime(
        s,
        "Perfect Blue",
        popularity=400,
        start_year=1998,
        score=85,
        episodes=1,
        format="MOVIE",
        studios=[w["madhouse"]],
        genres=["Horror"],
        source_material="NOVEL",
    )
    w["space_dandy"] = make_anime(
        s,
        "Space Dandy",
        popularity=100,
        start_year=2014,
        score=58,
        episodes=13,
        studios=[w["bones"]],
        genres=["Comedy"],
        tags=["Space"],
        source_material="ORIGINAL",
    )
    w["not_started"] = make_anime(
        s, "Next Year's Show", popularity=50, start_year=2027, end_year=None
    )

    w["edward"] = make_character(
        s, "Edward Elric", popularity=90, appears_in=[w["fma"], w["fmab"], w["shamballa"]]
    )
    w["gon"] = make_character(
        s, "Gon Freecss", popularity=80, appears_in=[w["hxh_1999"], w["hxh_2011"]]
    )
    w["luffy"] = make_character(s, "Monkey D. Luffy", popularity=100, appears_in=[w["one_piece"]])
    w["mima"] = make_character(s, "Mima Kirigoe", popularity=20, appears_in=[w["perfect_blue"]])
    w["dandy"] = make_character(s, "Dandy", popularity=10, appears_in=[w["space_dandy"]])
    return w


# slug → (params, expected answers). A param value starting with "@" is the id
# of that world entity; expected answers are world keys.
CASES: dict[str, tuple[dict[str, Any], set[str]]] = {
    "anime-by-studio": ({"studio": "@bones"}, {"fma", "fmab", "shamballa", "space_dandy"}),
    "anime-aired-in-year": ({"year": 2010}, {"fmab", "one_piece"}),
    "anime-premiered-in-year": ({"year": 1999}, {"hxh_1999", "one_piece"}),
    "anime-top-popular": ({"n": 3}, {"one_piece", "fmab", "hxh_2011"}),
    "anime-top-rated": ({"n": 3}, {"fmab", "hxh_2011", "one_piece"}),
    "anime-by-genre": ({"genre": "Action"}, {"fma", "fmab", "shamballa", "hxh_2011"}),
    "anime-by-two-genres": (
        {"genre": "Action", "genre2": "Adventure"},
        {"fma", "fmab", "hxh_2011"},
    ),
    "anime-by-genre-in-decade": (
        {"genre": "Adventure", "decade": 2000, "from": 2000, "to": 2009},
        {"fma", "fmab", "hxh_1999", "one_piece"},
    ),
    "anime-by-genre-and-studio": ({"genre": "Action", "studio": "@madhouse"}, {"hxh_2011"}),
    "anime-by-studio-in-decade": (
        {"studio": "@bones", "decade": 2010, "from": 2010, "to": 2019},
        {"fmab", "space_dandy"},
    ),
    "anime-top-popular-in-genre": ({"n": 2, "genre": "Action"}, {"fmab", "hxh_2011"}),
    "anime-top-rated-in-decade": (
        {"n": 2, "decade": 2000, "from": 2000, "to": 2009},
        {"fmab", "one_piece"},
    ),
    "anime-movie-in-decade": ({"decade": 1990, "from": 1990, "to": 1999}, {"perfect_blue"}),
    "anime-movie-by-genre": ({"genre": "Action"}, {"shamballa"}),
    "anime-movie-by-studio": ({"studio": "@madhouse"}, {"perfect_blue"}),
    "anime-rated-at-least": ({"score": 85}, {"fmab", "hxh_2011", "one_piece", "perfect_blue"}),
    "anime-rated-below": ({"score": 60, "max": 59}, {"space_dandy"}),
    "anime-currently-airing": ({"year": 2026}, {"one_piece"}),
    "anime-ran-for-years": ({"years": 3, "year": 2026}, {"hxh_2011", "one_piece"}),
    "franchise-with-movie": ({}, {"fma_franchise"}),
    "franchise-by-studio": ({"studio": "@madhouse"}, {"hxh_franchise"}),
    "franchise-aired-in-decade": (
        {"decade": 2010, "from": 2010, "to": 2019},
        {"fma_franchise", "hxh_franchise", "one_piece_franchise"},
    ),
    "franchise-with-min-anime": ({"n": 2}, {"fma_franchise", "hxh_franchise"}),
    "character-from-anime": ({"anime": "@fmab"}, {"edward"}),
    "character-from-franchise": ({"franchise": "@fma_franchise"}, {"edward"}),
    "character-from-studio-anime": ({"studio": "@bones"}, {"edward", "dandy"}),
    "character-from-anime-aired-in-year": ({"year": 1999}, {"gon", "luffy"}),
    "character-top-favourited": ({"n": 2}, {"luffy", "edward"}),
    "anime-by-tag": ({"tag": "Space"}, {"space_dandy"}),
    "anime-original": ({}, {"shamballa", "space_dandy"}),
    "anime-adapted-from": (
        {"source": "MANGA", "source_label": "manga"},
        {"fma", "fmab", "hxh_1999", "hxh_2011", "one_piece"},
    ),
    "anime-min-episodes": ({"episodes": 100}, {"hxh_2011"}),
    "tv-anime-13-or-fewer-episodes": ({}, {"space_dandy"}),
}

# The fixed choices F-020 lists for a template's params.
CHOICES: dict[str, list[dict[str, Any]]] = {
    "anime-top-popular": [{"n": n} for n in (25, 50, 100, 250, 500)],
    "anime-top-rated": [{"n": n} for n in (25, 50, 100, 250, 500)],
    "anime-top-popular-in-genre": [{"n": n} for n in (25, 50, 100)],
    "anime-top-rated-in-decade": [{"n": n} for n in (25, 50, 100, 250)],
    "anime-rated-at-least": [{"score": 80}, {"score": 85}],
    "anime-rated-below": [{"score": 60, "max": 59}, {"score": 65, "max": 64}],
    "anime-ran-for-years": [{"years": years} for years in (3, 5, 10)],
    "franchise-with-min-anime": [{"n": n} for n in (3, 5, 10)],
    "character-top-favourited": [{"n": n} for n in (25, 50, 100, 250)],
    "anime-adapted-from": [
        {"source": "MANGA", "source_label": "manga"},
        {"source": "LIGHT_NOVEL", "source_label": "light novel"},
        {"source": "VIDEO_GAME", "source_label": "video game"},
        {"source": "VISUAL_NOVEL", "source_label": "visual novel"},
    ],
    "anime-min-episodes": [{"episodes": 100}, {"episodes": 200}],
}


def list_answers(session: Session, world: World, template: TemplateDef, params: dict) -> list[str]:
    """The world keys of a template's answers, in the order returned."""
    key_of = {entity.id: key for key, entity in world.items()}
    resolved = {
        name: world[value[1:]].id if isinstance(value, str) and value.startswith("@") else value
        for name, value in params.items()
    }
    return [key_of[entity.id] for entity in session.scalars(template.answers(resolved))]


# --- the template list --------------------------------------------------------


def test_f020_every_template_has_a_case() -> None:
    assert set(BY_SLUG) == set(CASES)
    assert len(TEMPLATES) == len(BY_SLUG) == 33


@pytest.mark.parametrize("slug", sorted(CASES))
def test_f020_each_template_lists_its_answers(db_session: Session, world: World, slug: str) -> None:
    params, expected = CASES[slug]

    listed = list_answers(db_session, world, BY_SLUG[slug], params)

    assert sorted(listed) == sorted(expected)


def test_f020_answer_kinds_follow_the_spec_grouping() -> None:
    kinds = {template.slug: template.answer_kind for template in TEMPLATES}

    assert {slug for slug, kind in kinds.items() if kind == "franchise"} == FRANCHISE_SLUGS
    assert {slug for slug, kind in kinds.items() if kind == "character"} == CHARACTER_SLUGS
    # Everything else defaults to anime.
    assert set(kinds.values()) == {"anime", "franchise", "character"}
    assert TemplateDef(slug="x", text="x", where=()).answer_kind == "anime"


def test_f020_fixed_param_choices_match_the_spec() -> None:
    assert {t.slug: list(t.choices) for t in TEMPLATES if t.choices} == CHOICES


def test_f020_template_texts_only_use_placeholders_a_case_provides() -> None:
    for template in TEMPLATES:
        params, _ = CASES[template.slug]
        template.text.format(**params)  # KeyError on a placeholder no param fills


# --- object_where: the three character templates ------------------------------


def test_f020_character_from_franchise_appears_once(db_session: Session, world: World) -> None:
    # Edward appears in all three members; Gon is in another franchise.
    template = BY_SLUG["character-from-franchise"]

    assert list_answers(db_session, world, template, {"franchise": "@fma_franchise"}) == ["edward"]
    assert list_answers(db_session, world, template, {"franchise": "@hxh_franchise"}) == ["gon"]


def test_f020_character_from_studio_anime_appears_once(db_session: Session, world: World) -> None:
    # Edward's three anime are all by Bones; only one of Gon's two is by Madhouse.
    template = BY_SLUG["character-from-studio-anime"]

    assert list_answers(db_session, world, template, {"studio": "@bones"}) == ["edward", "dandy"]
    assert list_answers(db_session, world, template, {"studio": "@madhouse"}) == ["gon", "mima"]


def test_f020_character_from_anime_aired_in_year_appears_once(
    db_session: Session, world: World
) -> None:
    template = BY_SLUG["character-from-anime-aired-in-year"]

    # 2004: only the first Fullmetal Alchemist (of Edward's three) and One Piece aired.
    assert list_answers(db_session, world, template, {"year": 2004}) == ["luffy", "edward"]
    # 2014: Hunter x Hunter (2011) and Space Dandy both aired, as did One Piece.
    assert list_answers(db_session, world, template, {"year": 2014}) == ["luffy", "gon", "dandy"]


# --- franchise vs anime answers -----------------------------------------------


def test_f020_franchise_templates_give_one_answer_per_franchise(
    db_session: Session, world: World
) -> None:
    # All three Fullmetal Alchemist anime are by Bones: three anime answers, one franchise.
    params = {"studio": "@bones"}

    by_franchise = list_answers(db_session, world, BY_SLUG["franchise-by-studio"], params)
    by_anime = list_answers(db_session, world, BY_SLUG["anime-by-studio"], params)

    assert by_franchise == ["fma_franchise"]
    assert by_anime == ["fmab", "fma", "shamballa", "space_dandy"]


# --- seeding ------------------------------------------------------------------


def stored(session: Session) -> dict[str, PromptTemplate]:
    return {row.slug: row for row in session.scalars(select(PromptTemplate))}


def test_f020_seed_stores_every_template(db_session: Session) -> None:
    assert seed_templates.seed_templates(db_session) == 33

    rows = stored(db_session)
    assert set(rows) == set(BY_SLUG)
    for slug, row in rows.items():
        template = BY_SLUG[slug]
        assert row.text == template.text
        assert row.answer_kind == template.answer_kind
        assert row.answer_kind in ENTITY_KINDS
        assert row.query_def == template.query_def
        assert row.active is True

    by_studio = rows["anime-by-studio"]
    assert by_studio.text == "Name an anime by {studio}"
    assert by_studio.query_def == {"where": [{"predicate": "produced_by", "object": "$studio"}]}


def test_f020_seeding_again_updates_in_place_and_keeps_active(db_session: Session) -> None:
    seed_templates.seed_templates(db_session)
    before = stored(db_session)
    row = before["anime-by-studio"]
    row_id = row.id
    row.text = "Old wording"
    row.query_def = {"where": []}
    row.active = False
    db_session.flush()

    seed_templates.seed_templates(db_session)
    db_session.expire_all()

    assert db_session.scalar(select(func.count()).select_from(PromptTemplate)) == 33
    after = stored(db_session)["anime-by-studio"]
    assert after.id == row_id
    assert after.text == "Name an anime by {studio}"
    assert after.query_def == BY_SLUG["anime-by-studio"].query_def
    # Switching a template off is the owner's call; seeding does not undo it.
    assert after.active is False


def test_f020_seed_cli(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    assert seed_templates.main([], session=db_session) == 0

    assert len(stored(db_session)) == 33
    assert "Seeded 33 prompt templates" in capsys.readouterr().out
