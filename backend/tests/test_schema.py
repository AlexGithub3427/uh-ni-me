"""F-002: the database schema, tested against the migrated test database.

Most tests use plain SQL so they exercise what the migration created, not what
the ORM models claim. Two tests at the bottom tie the models to the migration.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

TABLES = {
    "entity",
    "entity_alias",
    "fact",
    "prompt_template",
    "prompt",
    "prompt_answer",
    "daily_puzzle",
    "player",
    "submission",
}
DAY = date(2026, 1, 15)
NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

Row = Mapping[str, Any]


# --- helpers -----------------------------------------------------------------


def insert(session: Session, table: str, **values: Any) -> Row:
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    statement = text(f"INSERT INTO {table} ({columns}) VALUES ({params}) RETURNING *")
    return session.execute(statement, values).mappings().one()


def assert_rejected(session: Session, constraint: str, table: str, **values: Any) -> None:
    """The insert must fail on exactly the named constraint."""
    with pytest.raises(IntegrityError) as error:
        with session.begin_nested():
            insert(session, table, **values)
    assert error.value.orig.diag.constraint_name == constraint


def make_entity(session: Session, kind: str = "anime", **values: Any) -> Row:
    values = {"canonical_name": f"Some {kind}", "popularity": 100} | values
    return insert(session, "entity", kind=kind, **values)


def make_prompt(session: Session, slug: str = "anime-by-studio") -> Row:
    template = insert(
        session,
        "prompt_template",
        slug=slug,
        text="Name an anime produced by {studio}",
        answer_kind="anime",
        query_def="{}",
    )
    return insert(
        session,
        "prompt",
        template_id=template["id"],
        params='{"studio": 1}',
        text="Name an anime produced by Bones",
    )


def make_started_submission(session: Session, **values: Any) -> dict[str, Any]:
    """A player, a prompt in DAY's puzzle, and the values for their submission."""
    prompt = make_prompt(session)
    insert(session, "daily_puzzle", day=DAY, position=1, prompt_id=prompt["id"])
    player = insert(session, "player", created_at=NOW)
    return {
        "player_id": player["id"],
        "day": DAY,
        "prompt_id": prompt["id"],
        "started_at": NOW,
    } | values


# --- structure ---------------------------------------------------------------


def test_f002_pg_trgm_extension_is_enabled(db_session: Session) -> None:
    names = db_session.execute(text("SELECT extname FROM pg_extension")).scalars().all()

    assert "pg_trgm" in names


def test_f002_all_tables_exist(db_session: Session) -> None:
    assert TABLES <= set(inspect(db_session.connection()).get_table_names())


def test_f002_indexes_exist(db_session: Session) -> None:
    rows = db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    )
    indexes = {name: definition for name, definition in rows}

    assert "gin (normalized gin_trgm_ops)" in indexes["ix_entity_alias_normalized_trgm"]
    assert "(franchise_id)" in indexes["ix_entity_franchise_id"]
    assert "(predicate, object_id)" in indexes["ix_fact_predicate_object_id"]
    assert "(predicate, value)" in indexes["ix_fact_predicate_value"]
    assert "(prompt_id, day)" in indexes["ix_daily_puzzle_prompt_id_day"]
    assert "(day, prompt_id)" in indexes["uq_daily_puzzle_day_prompt_id"]
    assert "(template_id, params)" in indexes["uq_prompt_template_id_params"]
    assert "(slug)" in indexes["uq_prompt_template_slug"]
    assert "(entity_id, normalized)" in indexes["uq_entity_alias_entity_id_normalized"]
    object_index = indexes["uq_fact_object_per_source"]
    assert "UNIQUE" in object_index
    assert "(subject_id, predicate, object_id, source)" in object_index
    assert "WHERE (object_id IS NOT NULL)" in object_index
    value_index = indexes["uq_fact_value_per_source"]
    assert "UNIQUE" in value_index
    assert "(subject_id, predicate, value, source)" in value_index
    assert "WHERE (value IS NOT NULL)" in value_index
    # The unique index already covers entity_id lookups; no separate index.
    assert not any(d.endswith("(entity_id)") for d in indexes.values())


def test_f002_only_the_columns_marked_null_are_nullable(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND is_nullable = 'YES' "
            "AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    )

    assert {tuple(row) for row in rows} == {
        ("entity", "start_year"),
        ("entity", "end_year"),
        ("entity", "score"),
        ("entity", "episodes"),
        ("entity", "anilist_id"),
        ("entity", "mal_id"),
        ("entity", "wikidata_id"),
        ("entity", "franchise_id"),
        ("fact", "object_id"),
        ("fact", "value"),
        ("submission", "finished_at"),
        ("submission", "raw_text"),
        ("submission", "matched_entity_id"),
        ("submission", "outcome"),
        ("submission", "points"),
        ("submission", "rarity_tier"),
    }


def test_f002_id_columns_are_always_generated_bigint_identities(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name, data_type, identity_generation "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'id' AND table_name = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    )
    columns = {table: (data_type, generation) for table, data_type, generation in rows}

    assert columns.pop("player") == ("uuid", None)
    assert set(columns) == {"entity", "entity_alias", "fact", "prompt_template", "prompt"} | {
        "submission"
    }
    assert set(columns.values()) == {("bigint", "ALWAYS")}


def test_f002_time_columns_are_timestamptz(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND column_name IN ('created_at', 'started_at', 'finished_at')"
        )
    )

    assert {tuple(row) for row in rows} == {
        ("created_at", "timestamp with time zone"),
        ("started_at", "timestamp with time zone"),
        ("finished_at", "timestamp with time zone"),
    }


def test_f002_defaults_are_filled_in(db_session: Session) -> None:
    prompt = make_prompt(db_session)
    template = db_session.execute(text("SELECT active FROM prompt_template")).one()
    answer = insert(
        db_session,
        "prompt_answer",
        prompt_id=prompt["id"],
        entity_id=make_entity(db_session)["id"],
        base_rarity=0.5,
    )
    insert(db_session, "daily_puzzle", day=DAY, position=1, prompt_id=prompt["id"])
    player = db_session.execute(text("INSERT INTO player DEFAULT VALUES RETURNING *")).one()
    submission = insert(
        db_session,
        "submission",
        player_id=player.id,
        day=DAY,
        prompt_id=prompt["id"],
        started_at=NOW,
    )

    assert template.active is True
    assert prompt["active"] is True
    assert answer["times_answered"] == 0
    assert player.id is not None
    assert player.created_at is not None
    assert submission["guess_count"] == 0
    assert submission["wrong_guesses"] == []
    assert submission["outcome"] is None


# --- entity ------------------------------------------------------------------


def test_f002_rejects_duplicate_kind_and_anilist_id(db_session: Session) -> None:
    make_entity(db_session, "anime", anilist_id=21)

    assert_rejected(
        db_session,
        "uq_entity_kind_anilist_id",
        "entity",
        kind="anime",
        canonical_name="Copy",
        popularity=1,
        anilist_id=21,
    )


def test_f002_allows_the_same_anilist_id_on_different_kinds(db_session: Session) -> None:
    make_entity(db_session, "anime", anilist_id=21)
    make_entity(db_session, "character", anilist_id=21)
    make_entity(db_session, "studio", anilist_id=21)
    make_entity(db_session, "franchise", anilist_id=21)


def test_f002_rejects_unknown_entity_kind(db_session: Session) -> None:
    assert_rejected(
        db_session, "ck_entity_kind", "entity", kind="staff", canonical_name="X", popularity=1
    )


@pytest.mark.parametrize("field", ["start_year", "end_year", "score", "episodes"])
def test_f002_rejects_anime_only_fields_on_other_kinds(db_session: Session, field: str) -> None:
    values = {"start_year": 2010} if field == "end_year" else {}
    assert_rejected(
        db_session,
        "ck_entity_anime_only_fields",
        "entity",
        kind="studio",
        canonical_name="Bones",
        popularity=1,
        **values,
        **{field: 50 if field == "score" else 2011},
    )


def test_f015_anime_has_a_nullable_integer_episode_count(db_session: Session) -> None:
    column_type = db_session.scalar(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'entity' AND column_name = 'episodes'"
        )
    )

    assert column_type == "integer"
    assert make_entity(db_session, episodes=25)["episodes"] == 25
    assert make_entity(db_session)["episodes"] is None


def test_f002_rejects_end_year_before_start_year(db_session: Session) -> None:
    assert_rejected(
        db_session,
        "ck_entity_year_order",
        "entity",
        kind="anime",
        canonical_name="X",
        popularity=1,
        start_year=2011,
        end_year=2010,
    )


def test_f002_rejects_end_year_without_start_year(db_session: Session) -> None:
    assert_rejected(
        db_session,
        "ck_entity_year_order",
        "entity",
        kind="anime",
        canonical_name="X",
        popularity=1,
        end_year=2010,
    )


def test_f002_allows_still_airing_and_single_year_anime(db_session: Session) -> None:
    make_entity(db_session, start_year=1999, end_year=None)
    make_entity(db_session, start_year=2011, end_year=2011)


@pytest.mark.parametrize("score", [-1, 101])
def test_f002_rejects_score_outside_0_to_100(db_session: Session, score: int) -> None:
    assert_rejected(
        db_session,
        "ck_entity_score_range",
        "entity",
        kind="anime",
        canonical_name="X",
        popularity=1,
        score=score,
    )


def test_f002_rejects_franchise_id_on_non_anime(db_session: Session) -> None:
    franchise = make_entity(db_session, "franchise")

    assert_rejected(
        db_session,
        "ck_entity_franchise_anime_only",
        "entity",
        kind="character",
        canonical_name="X",
        popularity=1,
        franchise_id=franchise["id"],
    )


# --- entity_alias ------------------------------------------------------------


def test_f002_rejects_empty_normalized_alias(db_session: Session) -> None:
    anime = make_entity(db_session)

    assert_rejected(
        db_session,
        "ck_entity_alias_normalized_not_empty",
        "entity_alias",
        entity_id=anime["id"],
        alias="!!!",
        normalized="",
    )


def test_f002_rejects_duplicate_normalized_alias_on_one_entity(db_session: Session) -> None:
    anime = make_entity(db_session)
    insert(db_session, "entity_alias", entity_id=anime["id"], alias="Shōnen", normalized="shonen")

    assert_rejected(
        db_session,
        "uq_entity_alias_entity_id_normalized",
        "entity_alias",
        entity_id=anime["id"],
        alias="Shounen",
        normalized="shonen",
    )


# --- fact --------------------------------------------------------------------


def test_f002_rejects_fact_with_both_object_and_value(db_session: Session) -> None:
    anime, studio = make_entity(db_session), make_entity(db_session, "studio")

    assert_rejected(
        db_session,
        "ck_fact_object_xor_value",
        "fact",
        subject_id=anime["id"],
        predicate="produced_by",
        object_id=studio["id"],
        value="Bones",
        source="anilist",
    )


def test_f002_rejects_fact_with_neither_object_nor_value(db_session: Session) -> None:
    anime = make_entity(db_session)

    assert_rejected(
        db_session,
        "ck_fact_object_xor_value",
        "fact",
        subject_id=anime["id"],
        predicate="produced_by",
        source="anilist",
    )


def test_f002_same_object_fact_allowed_from_two_sources_but_not_twice_from_one(
    db_session: Session,
) -> None:
    anime, studio = make_entity(db_session), make_entity(db_session, "studio")
    fact = {"subject_id": anime["id"], "predicate": "produced_by", "object_id": studio["id"]}
    insert(db_session, "fact", **fact, source="anilist")
    insert(db_session, "fact", **fact, source="wikidata")

    assert_rejected(db_session, "uq_fact_object_per_source", "fact", **fact, source="anilist")


def test_f002_same_value_fact_allowed_from_two_sources_but_not_twice_from_one(
    db_session: Session,
) -> None:
    anime = make_entity(db_session)
    fact = {"subject_id": anime["id"], "predicate": "genre", "value": "Action"}
    insert(db_session, "fact", **fact, source="anilist")
    insert(db_session, "fact", **fact, source="wikidata")

    assert_rejected(db_session, "uq_fact_value_per_source", "fact", **fact, source="anilist")


# --- prompts -----------------------------------------------------------------


def test_f002_rejects_unknown_answer_kind(db_session: Session) -> None:
    assert_rejected(
        db_session,
        "ck_prompt_template_answer_kind",
        "prompt_template",
        slug="x",
        text="Name a voice actor",
        answer_kind="staff",
        query_def="{}",
    )


def test_f002_rejects_duplicate_template_slug(db_session: Session) -> None:
    make_prompt(db_session, slug="anime-by-studio")

    assert_rejected(
        db_session,
        "uq_prompt_template_slug",
        "prompt_template",
        slug="anime-by-studio",
        text="Again",
        answer_kind="anime",
        query_def="{}",
    )


def test_f002_rejects_duplicate_prompt_params_regardless_of_key_order(
    db_session: Session,
) -> None:
    template_id = make_prompt(db_session)["template_id"]
    insert(db_session, "prompt", template_id=template_id, params='{"a": 1, "b": 2}', text="x")

    assert_rejected(
        db_session,
        "uq_prompt_template_id_params",
        "prompt",
        template_id=template_id,
        params='{"b": 2, "a": 1}',
        text="y",
    )


@pytest.mark.parametrize("base_rarity", [-0.1, 1.1])
def test_f002_rejects_base_rarity_outside_0_to_1(db_session: Session, base_rarity: float) -> None:
    assert_rejected(
        db_session,
        "ck_prompt_answer_base_rarity_range",
        "prompt_answer",
        prompt_id=make_prompt(db_session)["id"],
        entity_id=make_entity(db_session)["id"],
        base_rarity=base_rarity,
    )


def test_f002_rejects_negative_times_answered(db_session: Session) -> None:
    assert_rejected(
        db_session,
        "ck_prompt_answer_times_answered_min",
        "prompt_answer",
        prompt_id=make_prompt(db_session)["id"],
        entity_id=make_entity(db_session)["id"],
        base_rarity=0.5,
        times_answered=-1,
    )


def test_f002_rejects_the_same_answer_twice_for_one_prompt(db_session: Session) -> None:
    answer = {
        "prompt_id": make_prompt(db_session)["id"],
        "entity_id": make_entity(db_session)["id"],
        "base_rarity": 0.5,
    }
    insert(db_session, "prompt_answer", **answer)

    assert_rejected(db_session, "pk_prompt_answer", "prompt_answer", **answer)


# --- daily_puzzle ------------------------------------------------------------


def test_f002_rejects_position_below_1(db_session: Session) -> None:
    assert_rejected(
        db_session,
        "ck_daily_puzzle_position_min",
        "daily_puzzle",
        day=DAY,
        position=0,
        prompt_id=make_prompt(db_session)["id"],
    )


def test_f002_rejects_the_same_prompt_twice_in_one_day(db_session: Session) -> None:
    prompt = make_prompt(db_session)
    insert(db_session, "daily_puzzle", day=DAY, position=1, prompt_id=prompt["id"])

    assert_rejected(
        db_session,
        "uq_daily_puzzle_day_prompt_id",
        "daily_puzzle",
        day=DAY,
        position=2,
        prompt_id=prompt["id"],
    )


def test_f002_rejects_two_prompts_at_one_position(db_session: Session) -> None:
    first, second = make_prompt(db_session, "a"), make_prompt(db_session, "b")
    insert(db_session, "daily_puzzle", day=DAY, position=1, prompt_id=first["id"])

    assert_rejected(
        db_session, "pk_daily_puzzle", "daily_puzzle", day=DAY, position=1, prompt_id=second["id"]
    )


# --- submission --------------------------------------------------------------


def test_f002_rejects_duplicate_submission_for_player_day_and_prompt(
    db_session: Session,
) -> None:
    values = make_started_submission(db_session)
    insert(db_session, "submission", **values)

    assert_rejected(db_session, "uq_submission_player_id_day_prompt_id", "submission", **values)


def test_f002_rejects_submission_for_prompt_not_in_that_days_puzzle(
    db_session: Session,
) -> None:
    values = make_started_submission(db_session) | {"day": date(2026, 1, 16)}

    assert_rejected(db_session, "fk_submission_day_prompt_id_daily_puzzle", "submission", **values)


def test_f002_rejects_outcome_without_finished_at(db_session: Session) -> None:
    values = make_started_submission(db_session, outcome="expired", points=0)

    assert_rejected(db_session, "ck_submission_outcome_finished_together", "submission", **values)


def test_f002_rejects_finished_at_without_outcome(db_session: Session) -> None:
    values = make_started_submission(db_session, finished_at=NOW)

    assert_rejected(db_session, "ck_submission_outcome_finished_together", "submission", **values)


def test_f002_rejects_accepted_outcome_without_matched_entity(db_session: Session) -> None:
    values = make_started_submission(
        db_session, outcome="accepted", finished_at=NOW, points=10, rarity_tier="larp"
    )

    assert_rejected(db_session, "ck_submission_accepted_has_match", "submission", **values)


def test_f002_rejects_matched_entity_on_expired_outcome(db_session: Session) -> None:
    values = make_started_submission(
        db_session,
        outcome="expired",
        finished_at=NOW,
        points=0,
        matched_entity_id=make_entity(db_session)["id"],
    )

    assert_rejected(db_session, "ck_submission_accepted_has_match", "submission", **values)


def test_f002_rejects_unknown_outcome(db_session: Session) -> None:
    values = make_started_submission(db_session, outcome="skipped", finished_at=NOW)

    assert_rejected(db_session, "ck_submission_outcome", "submission", **values)


def test_f002_rejects_unknown_rarity_tier(db_session: Session) -> None:
    values = make_started_submission(
        db_session,
        outcome="accepted",
        finished_at=NOW,
        points=85,
        rarity_tier="ebk",
        matched_entity_id=make_entity(db_session)["id"],
    )

    assert_rejected(db_session, "ck_submission_rarity_tier", "submission", **values)


@pytest.mark.parametrize("tier", ["larp", "normie", "niche", "weeb", "uh-ni-me"])
def test_f002_accepts_an_accepted_submission_in_every_tier(db_session: Session, tier: str) -> None:
    values = make_started_submission(
        db_session,
        outcome="accepted",
        finished_at=NOW,
        raw_text="mob psycho",
        points=60,
        rarity_tier=tier,
        matched_entity_id=make_entity(db_session)["id"],
        guess_count=2,
        wrong_guesses=["mob", "psycho"],
    )

    row = insert(db_session, "submission", **values)

    assert row["rarity_tier"] == tier
    assert row["wrong_guesses"] == ["mob", "psycho"]


# --- deletes -----------------------------------------------------------------


def test_f002_deleting_an_entity_removes_its_aliases_facts_and_answers(
    db_session: Session,
) -> None:
    anime, studio = make_entity(db_session), make_entity(db_session, "studio")
    other = make_entity(db_session, canonical_name="Other anime")
    insert(db_session, "entity_alias", entity_id=studio["id"], alias="Bones", normalized="bones")
    insert(
        db_session,
        "fact",
        subject_id=anime["id"],
        predicate="produced_by",
        object_id=studio["id"],
        source="anilist",
    )
    insert(db_session, "fact", subject_id=studio["id"], predicate="x", value="y", source="anilist")
    insert(db_session, "fact", subject_id=other["id"], predicate="x", value="y", source="anilist")
    prompt = make_prompt(db_session)
    insert(
        db_session, "prompt_answer", prompt_id=prompt["id"], entity_id=studio["id"], base_rarity=0
    )

    db_session.execute(text("DELETE FROM entity WHERE id = :id"), {"id": studio["id"]})

    def count(table: str) -> int:
        return db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    assert count("entity_alias") == 0
    assert count("fact") == 1  # only the unrelated anime's fact is left
    assert count("prompt_answer") == 0
    assert count("entity") == 2


def test_f002_rejects_deleting_an_entity_a_player_was_awarded(db_session: Session) -> None:
    anime = make_entity(db_session)
    values = make_started_submission(
        db_session,
        outcome="accepted",
        finished_at=NOW,
        points=10,
        rarity_tier="larp",
        matched_entity_id=anime["id"],
    )
    insert(db_session, "submission", **values)

    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM entity WHERE id = :id"), {"id": anime["id"]})
    assert error.value.orig.diag.constraint_name == "fk_submission_matched_entity_id_entity"


def test_f002_rejects_deleting_a_franchise_that_still_has_members(db_session: Session) -> None:
    franchise = make_entity(db_session, "franchise")
    make_entity(db_session, franchise_id=franchise["id"])

    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM entity WHERE id = :id"), {"id": franchise["id"]})
    assert error.value.orig.diag.constraint_name == "fk_entity_franchise_id_entity"


# --- migration and models ----------------------------------------------------


def test_f002_downgrade_to_base_then_upgrade_to_head_runs_cleanly(
    db_engine: Engine, alembic_config: Config
) -> None:
    def tables() -> set[str]:
        with db_engine.connect() as connection:
            return set(inspect(connection).get_table_names())

    command.downgrade(alembic_config, "base")
    assert not TABLES & tables()

    command.upgrade(alembic_config, "head")
    assert TABLES <= tables()


def test_f002_models_match_the_migrated_schema(db_engine: Engine) -> None:
    from app.models import Base

    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert set(Base.metadata.tables) == TABLES
    assert differences == []


def test_f002_models_round_trip_through_the_orm(db_session: Session) -> None:
    from app.models import Entity, EntityAlias, Fact

    studio = Entity(kind="studio", canonical_name="Bones", popularity=5000)
    anime = Entity(
        kind="anime", canonical_name="Mob Psycho 100", popularity=400000, score=84, start_year=2016
    )
    db_session.add_all([studio, anime])
    db_session.flush()
    db_session.add_all(
        [
            EntityAlias(entity_id=anime.id, alias="Mob Psycho 100", normalized="mobpsycho100"),
            Fact(
                subject_id=anime.id, predicate="produced_by", object_id=studio.id, source="anilist"
            ),
        ]
    )
    db_session.flush()
    db_session.expire_all()

    fact = db_session.query(Fact).one()
    assert db_session.get(Entity, fact.subject_id).canonical_name == "Mob Psycho 100"
    assert db_session.get(Entity, fact.object_id).kind == "studio"
    assert db_session.get(Entity, anime.id).end_year is None
