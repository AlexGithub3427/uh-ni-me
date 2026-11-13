"""F-011: AniList source records → entity, entity_alias and fact rows, and the ingest CLI."""

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Entity, EntityAlias, Fact
from app.services.normalize import normalize
from ingest import run
from ingest.anilist import AniListAnime
from ingest.normalizer import upsert_anilist
from tests.test_anilist_client import ATTACK_ON_TITAN, DEMON_SLAYER, FakeAniList, _client

# --- helpers -----------------------------------------------------------------


def make_anime(id: int, title: str | dict[str, str] | None = None, **fields: Any) -> AniListAnime:
    """A finished TV anime; override any AniList field. A plain title is the romaji one."""
    record: dict[str, Any] = {
        "id": id,
        "title": title if isinstance(title, dict) else {"romaji": title or f"Anime {id}"},
        "popularity": 1000,
        "status": "FINISHED",
        "format": "TV",
        "start_date": {"year": 2010},
        "end_date": {"year": 2010},
    } | fields
    return AniListAnime.model_validate(record)


def relation(relation_type: str, id: int, type: str = "ANIME") -> dict[str, Any]:
    return {"relation_type": relation_type, "id": id, "type": type}


def studio(id: int, name: str, **fields: Any) -> dict[str, Any]:
    return {"id": id, "name": name, "favourites": 10, "is_animation_studio": True} | fields


def character(id: int, full: str, **fields: Any) -> dict[str, Any]:
    return {"id": id, "name": {"full": full}, "favourites": 5, "role": "MAIN"} | fields


def entity(session: Session, kind: str, anilist_id: int) -> Entity:
    return session.scalars(
        select(Entity).where(Entity.kind == kind, Entity.anilist_id == anilist_id)
    ).one()


def franchise_of(session: Session, anime_id: int) -> Entity:
    franchise_id = entity(session, "anime", anime_id).franchise_id
    assert franchise_id is not None
    return session.get_one(Entity, franchise_id)


def aliases(session: Session, entity_id: int) -> set[str]:
    return set(session.scalars(select(EntityAlias.alias).where(EntityAlias.entity_id == entity_id)))


def facts(session: Session, subject: Entity, predicate: str) -> set[Any]:
    """The objects (as ``(kind, anilist_id)``) or values of a subject's facts."""
    rows = session.execute(
        select(Fact.value, Entity.kind, Entity.anilist_id)
        .outerjoin(Entity, Entity.id == Fact.object_id)
        .where(Fact.subject_id == subject.id, Fact.predicate == predicate)
    )
    return {value if value is not None else (kind, anilist_id) for value, kind, anilist_id in rows}


def counts(session: Session) -> tuple[int, int, int]:
    return tuple(  # type: ignore[return-value]
        session.scalar(select(func.count()).select_from(model))
        for model in (Entity, EntityAlias, Fact)
    )


def fixture_records(tmp_path: Path) -> list[AniListAnime]:
    """Attack on Titan and Demon Slayer, as the F-010 client returns them."""
    return _client(FakeAniList(), tmp_path).fetch_top_anime(2)


# --- Facts -------------------------------------------------------------------


def test_f011_writes_produced_by_format_genre_and_appears_in_facts(
    db_session: Session, tmp_path: Path
) -> None:
    records = fixture_records(tmp_path)

    upsert_anilist(db_session, records)

    aot = entity(db_session, "anime", ATTACK_ON_TITAN)
    assert facts(db_session, aot, "format") == {"TV"}
    assert facts(db_session, aot, "genre") == {"Action", "Drama", "Fantasy", "Mystery"}
    produced_by = facts(db_session, aot, "produced_by")
    studios = {s.id: s for s in records[0].studios}
    assert produced_by == {("studio", s.id) for s in studios.values() if s.is_animation_studio}
    assert {studios[id].name for _, id in produced_by} == {"WIT STUDIO", "Production I.G"}

    for record in records:
        assert record.characters
        anime = entity(db_session, "anime", record.id)
        for source_character in record.characters:
            subject = entity(db_session, "character", source_character.id)
            assert ("anime", anime.anilist_id) in facts(db_session, subject, "appears_in")

    assert set(db_session.scalars(select(Fact.source))) == {"anilist"}
    assert set(db_session.scalars(select(Fact.predicate))) == {
        "produced_by",
        "appears_in",
        "format",
        "genre",
    }


def test_f011_only_animation_studios_get_produced_by_facts(db_session: Session) -> None:
    record = make_anime(
        1,
        studios=[
            studio(10, "Bones", is_main=True),
            studio(11, "Aniplex", is_animation_studio=False),
        ],
    )

    upsert_anilist(db_session, [record])

    assert facts(db_session, entity(db_session, "anime", 1), "produced_by") == {("studio", 10)}
    assert db_session.scalar(select(func.count()).where(Entity.kind == "studio")) == 1


def test_f011_character_shared_by_two_anime_is_one_entity_with_two_facts(
    db_session: Session,
) -> None:
    records = [
        make_anime(1, characters=[character(100, "Mob")]),
        make_anime(2, characters=[character(100, "Mob")]),
    ]

    upsert_anilist(db_session, records)

    mob = entity(db_session, "character", 100)
    assert facts(db_session, mob, "appears_in") == {("anime", 1), ("anime", 2)}


# --- Entity fields -----------------------------------------------------------


def test_f011_years_come_from_start_and_end_dates(db_session: Session) -> None:
    records = [
        make_anime(1, start_date={"year": 2013, "month": 4}, end_date={"year": 2014}),
        make_anime(2, status="RELEASING", start_date={"year": 1999}, end_date={}),
        make_anime(3, start_date={"year": 2006}, end_date={}),
        make_anime(4, status="NOT_YET_RELEASED", start_date={}, end_date={}),
    ]

    upsert_anilist(db_session, records)

    years = {
        id: (e.start_year, e.end_year)
        for id in (1, 2, 3, 4)
        for e in [entity(db_session, "anime", id)]
    }
    assert years == {
        1: (2013, 2014),
        2: (1999, None),  # still airing
        3: (2006, 2006),  # finished with no end date
        4: (None, None),
    }


def test_f011_years_and_score_are_never_set_for_other_kinds(
    db_session: Session, tmp_path: Path
) -> None:
    upsert_anilist(db_session, fixture_records(tmp_path))

    others = db_session.scalars(select(Entity).where(Entity.kind != "anime")).all()
    assert {e.kind for e in others} == {"character", "studio", "franchise"}
    assert all(e.start_year is None and e.end_year is None and e.score is None for e in others)


def test_f011_popularity_is_popularity_for_anime_and_favourites_otherwise(
    db_session: Session,
) -> None:
    record = make_anime(
        1,
        popularity=5000,
        studios=[studio(10, "Bones", favourites=70)],
        characters=[character(100, "Mob", favourites=900), character(101, "Dimple")],
    )
    record.characters[1].favourites = None

    upsert_anilist(db_session, [record])

    assert entity(db_session, "anime", 1).popularity == 5000
    assert entity(db_session, "studio", 10).popularity == 70
    assert entity(db_session, "character", 100).popularity == 900
    assert entity(db_session, "character", 101).popularity == 0


def test_f011_score_is_average_score_or_null(db_session: Session) -> None:
    upsert_anilist(db_session, [make_anime(1, average_score=85), make_anime(2)])

    assert entity(db_session, "anime", 1).score == 85
    assert entity(db_session, "anime", 2).score is None


# --- Aliases -----------------------------------------------------------------


def test_f011_every_title_variant_becomes_an_alias(db_session: Session, tmp_path: Path) -> None:
    upsert_anilist(db_session, fixture_records(tmp_path))

    aot = entity(db_session, "anime", ATTACK_ON_TITAN)
    assert aot.canonical_name == "Attack on Titan"
    names = aliases(db_session, aot.id)
    assert {"Attack on Titan", "Shingeki no Kyojin", "進撃の巨人", "SnK", "AoT"} <= names
    assert "Атака титанов" in names

    stored = db_session.execute(
        select(EntityAlias.alias, EntityAlias.normalized).where(EntityAlias.entity_id == aot.id)
    ).all()
    assert all(normalized == normalize(alias) for alias, normalized in stored)


def test_f011_character_and_studio_names_become_aliases(db_session: Session) -> None:
    record = make_anime(
        1,
        studios=[studio(10, "Bones")],
        characters=[
            character(
                100,
                "Shigeo Kageyama",
                name={"full": "Shigeo Kageyama", "native": "影山茂夫", "alternative": ["Mob"]},
            )
        ],
    )

    upsert_anilist(db_session, [record])

    mob = entity(db_session, "character", 100)
    assert mob.canonical_name == "Shigeo Kageyama"
    assert aliases(db_session, mob.id) == {"Shigeo Kageyama", "影山茂夫", "Mob"}
    assert aliases(db_session, entity(db_session, "studio", 10).id) == {"Bones"}


def test_f011_skips_names_with_an_empty_or_duplicate_match_key(db_session: Session) -> None:
    record = make_anime(
        1, title={"romaji": "Re:Zero", "english": "Re Zero"}, synonyms=["!?", "ReZero", ""]
    )

    upsert_anilist(db_session, [record])

    anime = entity(db_session, "anime", 1)
    assert anime.canonical_name == "Re Zero"
    assert aliases(db_session, anime.id) == {"Re Zero"}


# --- Franchises --------------------------------------------------------------


def test_f011_related_anime_share_a_franchise_and_standalone_gets_its_own(
    db_session: Session,
) -> None:
    records = [
        make_anime(1, relations=[relation("SEQUEL", 2)]),
        make_anime(2, relations=[relation("PREQUEL", 1), relation("SIDE_STORY", 3)]),
        make_anime(3, relations=[relation("PARENT", 2)]),
        make_anime(4),
        # Not franchise relations: an adaptation, a crossover, a spin-off and a manga parent.
        make_anime(
            5,
            relations=[
                relation("ADAPTATION", 1),
                relation("CHARACTER", 1),
                relation("SPIN_OFF", 1),
                relation("PARENT", 4, type="MANGA"),
            ],
        ),
    ]

    upsert_anilist(db_session, records)

    franchise_ids = {id: entity(db_session, "anime", id).franchise_id for id in range(1, 6)}
    assert franchise_ids[1] == franchise_ids[2] == franchise_ids[3]
    assert len(set(franchise_ids.values())) == 3
    for franchise_id in franchise_ids.values():
        assert db_session.get_one(Entity, franchise_id).kind == "franchise"
    assert db_session.scalar(select(func.count()).where(Entity.kind == "franchise")) == 3


def test_f011_anime_linked_through_an_unfetched_anime_share_a_franchise(
    db_session: Session,
) -> None:
    # Season 2 (id 99) is outside the top N, but seasons 1 and 3 both point at it.
    records = [
        make_anime(1, relations=[relation("SEQUEL", 99)]),
        make_anime(3, relations=[relation("PREQUEL", 99)]),
    ]

    upsert_anilist(db_session, records)

    assert franchise_of(db_session, 1).id == franchise_of(db_session, 3).id


def test_f011_franchise_is_built_from_its_members(db_session: Session) -> None:
    records = [
        make_anime(
            30,
            title={"romaji": "Shingeki no Kyojin Season 2", "english": "Attack on Titan Season 2"},
            popularity=900,
            start_date={"year": 2017},
            relations=[relation("PREQUEL", 20)],
        ),
        make_anime(
            20,
            title={"romaji": "Shingeki no Kyojin", "english": "Attack on Titan"},
            synonyms=["AoT"],
            popularity=500,
            average_score=85,
            start_date={"year": 2013},
        ),
        make_anime(
            10,
            "Shingeki no Kyojin: The Final Season",
            popularity=700,
            start_date={},
            end_date={},
            status="NOT_YET_RELEASED",
            relations=[relation("PREQUEL", 30)],
        ),
    ]

    upsert_anilist(db_session, records)

    franchise = franchise_of(db_session, 30)
    assert franchise.kind == "franchise"
    assert franchise.anilist_id == 20  # earliest start_year; an unknown year never wins
    assert franchise.canonical_name == "Attack on Titan"
    assert franchise.popularity == 900
    assert franchise.franchise_id is None
    assert aliases(db_session, franchise.id) == {
        "Attack on Titan",
        "Shingeki no Kyojin",
        "AoT",
        "Attack on Titan Season 2",
        "Shingeki no Kyojin Season 2",
        "Shingeki no Kyojin: The Final Season",
    }


def test_f011_franchise_root_tie_goes_to_the_lowest_anilist_id(db_session: Session) -> None:
    records = [
        make_anime(8, "Later id", relations=[relation("SIDE_STORY", 7)]),
        make_anime(7, "Lower id"),
    ]

    upsert_anilist(db_session, records)

    franchise = franchise_of(db_session, 8)
    assert (franchise.anilist_id, franchise.canonical_name) == (7, "Lower id")


# --- Re-running --------------------------------------------------------------


def test_f011_rerun_creates_no_duplicates(db_session: Session, tmp_path: Path) -> None:
    records = fixture_records(tmp_path)
    upsert_anilist(db_session, records)
    before = counts(db_session)
    entity_ids = set(db_session.scalars(select(Entity.id)))

    upsert_anilist(db_session, records)

    assert counts(db_session) == before
    assert set(db_session.scalars(select(Entity.id))) == entity_ids


def test_f011_rerun_updates_changed_fields(db_session: Session) -> None:
    upsert_anilist(db_session, [make_anime(1, "Old name", status="RELEASING", end_date={})])
    entity_id = entity(db_session, "anime", 1).id

    upsert_anilist(
        db_session,
        [make_anime(1, "New name", popularity=2000, average_score=77, end_date={"year": 2011})],
    )
    db_session.expire_all()

    anime = entity(db_session, "anime", 1)
    assert anime.id == entity_id
    assert (anime.canonical_name, anime.popularity, anime.score) == ("New name", 2000, 77)
    assert anime.end_year == 2011
    assert franchise_of(db_session, 1).popularity == 2000
    assert aliases(db_session, anime.id) == {"Old name", "New name"}


def test_f011_fact_that_disappears_upstream_is_removed(db_session: Session) -> None:
    before = make_anime(
        1,
        genres=["Action", "Comedy"],
        studios=[studio(10, "Bones"), studio(11, "MAPPA")],
        characters=[character(100, "Mob"), character(101, "Dimple")],
    )
    other = make_anime(2, characters=[character(101, "Dimple")])
    upsert_anilist(db_session, [before, other])
    anime = entity(db_session, "anime", 1)
    # Another source asserts a fact AniList is about to drop; it must survive.
    db_session.add(Fact(subject_id=anime.id, predicate="genre", value="Comedy", source="mal"))
    db_session.flush()

    after = make_anime(
        1,
        format="MOVIE",
        genres=["Action"],
        studios=[studio(10, "Bones")],
        characters=[character(100, "Mob")],
    )
    upsert_anilist(db_session, [after])

    assert facts(db_session, anime, "format") == {"MOVIE"}
    assert facts(db_session, anime, "produced_by") == {("studio", 10)}
    sources = dict(
        db_session.execute(
            select(Fact.value, Fact.source).where(
                Fact.subject_id == anime.id, Fact.predicate == "genre"
            )
        ).all()
    )
    assert sources == {"Action": "anilist", "Comedy": "mal"}
    # Dimple left anime 1 but is still in anime 2, which this run did not refetch.
    dimple = entity(db_session, "character", 101)
    assert facts(db_session, dimple, "appears_in") == {("anime", 2)}
    assert facts(db_session, entity(db_session, "character", 100), "appears_in") == {("anime", 1)}


# --- CLI ---------------------------------------------------------------------


def test_f011_cli_fetches_and_upserts(db_session: Session, tmp_path: Path) -> None:
    api = FakeAniList()

    exit_code = run.main(
        ["--source", "anilist", "--limit", "2"],
        client=_client(api, tmp_path),
        session=db_session,
    )

    assert exit_code == 0
    assert api.requests
    anime_ids = set(db_session.scalars(select(Entity.anilist_id).where(Entity.kind == "anime")))
    assert anime_ids == {ATTACK_ON_TITAN, DEMON_SLAYER}


def test_f011_cli_limit_caps_how_many_anime_are_ingested(
    db_session: Session, tmp_path: Path
) -> None:
    run.main(
        ["--source", "anilist", "--limit", "1"],
        client=_client(FakeAniList(), tmp_path),
        session=db_session,
    )

    anime_ids = set(db_session.scalars(select(Entity.anilist_id).where(Entity.kind == "anime")))
    assert anime_ids == {ATTACK_ON_TITAN}


def test_f011_cli_rejects_an_unknown_source(db_session: Session, capsys: Any) -> None:
    try:
        run.main(["--source", "imdb", "--limit", "1"], session=db_session)
    except SystemExit as exit:
        assert exit.code == 2
    else:
        raise AssertionError("expected the CLI to reject --source imdb")
    assert "invalid choice" in capsys.readouterr().err
    assert db_session.scalar(select(func.count()).select_from(Entity)) == 0
