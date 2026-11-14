"""F-020: the query_def interpreter, one condition type at a time."""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.services.query_def import QueryDefError, answer_select
from tests.factories import (
    add_fact,
    make_anime,
    make_character,
    make_franchise,
    make_studio,
    names,
)


def answers(
    session: Session,
    where: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    *,
    answer_kind: str = "anime",
) -> set[str]:
    return set(names(session, answer_select(answer_kind, {"where": where}, params or {})))


# --- facts --------------------------------------------------------------------


def test_f020_predicate_object_lists_the_subjects_of_matching_facts(db_session: Session) -> None:
    bones = make_studio(db_session, "Bones")
    mappa = make_studio(db_session, "MAPPA")
    make_anime(db_session, "Mob Psycho 100", studios=[bones])
    make_anime(db_session, "Jujutsu Kaisen", studios=[mappa])
    make_anime(db_session, "No Studio")

    where = [{"predicate": "produced_by", "object": "$studio"}]

    assert answers(db_session, where, {"studio": bones.id}) == {"Mob Psycho 100"}
    assert answers(db_session, where, {"studio": mappa.id}) == {"Jujutsu Kaisen"}


def test_f020_predicate_value_conditions_are_anded(db_session: Session) -> None:
    make_anime(db_session, "Your Name", genres=["Romance", "Drama"], format="MOVIE")
    make_anime(db_session, "Toradora!", genres=["Romance"])
    make_anime(db_session, "Akira", genres=["Action"], format="MOVIE")

    romance = {"predicate": "genre", "value": "$genre"}
    movie = {"predicate": "format", "value": "MOVIE"}

    assert answers(db_session, [romance], {"genre": "Romance"}) == {"Your Name", "Toradora!"}
    assert answers(db_session, [romance, movie], {"genre": "Romance"}) == {"Your Name"}


def test_f020_a_fact_asserted_by_two_sources_gives_one_answer(db_session: Session) -> None:
    anime = make_anime(db_session, "Akira", genres=["Action"])
    add_fact(db_session, anime, "genre", value="Action", source="mal")

    statement = answer_select("anime", {"where": [{"predicate": "genre", "value": "Action"}]}, {})

    assert names(db_session, statement) == ["Akira"]


def test_f020_answers_are_only_entities_of_the_answer_kind(db_session: Session) -> None:
    anime = make_anime(db_session, "Akira")
    make_character(db_session, "Kaneda", appears_in=[anime])

    assert answers(db_session, [], answer_kind="anime") == {"Akira"}
    assert answers(db_session, [], answer_kind="character") == {"Kaneda"}


def test_f020_a_missing_param_raises(db_session: Session) -> None:
    with pytest.raises(QueryDefError, match="studio"):
        answer_select("anime", {"where": [{"predicate": "produced_by", "object": "$studio"}]}, {})


# --- field --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"field": "start_year", "eq": 2005}, {"From 2005"}),
        ({"field": "start_year", "between": [2000, 2005]}, {"From 2000", "From 2005"}),
        ({"field": "score", "gte": 80}, {"From 2005", "From 2010"}),
        ({"field": "score", "lte": 80}, {"From 2000", "From 2005"}),
        ({"field": "score", "is_null": True}, {"Unscored"}),
        ({"field": "score", "is_null": False}, {"From 2000", "From 2005", "From 2010"}),
        ({"field": "episodes", "gte": 100}, {"From 2000"}),
        ({"field": "end_year", "lte": 2005}, {"From 2000", "From 2005"}),
    ],
)
def test_f020_field_operators(
    db_session: Session, condition: dict[str, Any], expected: set[str]
) -> None:
    make_anime(db_session, "From 2000", start_year=2000, score=70, episodes=100)
    make_anime(db_session, "From 2005", start_year=2005, score=80, episodes=12)
    make_anime(db_session, "From 2010", start_year=2010, score=90)
    # A NULL score fails gte and lte alike.
    make_anime(db_session, "Unscored", start_year=2020, score=None)

    assert answers(db_session, [condition]) == expected


def test_f020_field_values_can_be_params(db_session: Session) -> None:
    make_anime(db_session, "From 2000", start_year=2000)
    make_anime(db_session, "From 2005", start_year=2005)
    make_anime(db_session, "From 2010", start_year=2010)

    where = [{"field": "start_year", "between": ["$from", "$to"]}]

    assert answers(db_session, where, {"from": 2001, "to": 2010}) == {"From 2005", "From 2010"}


def test_f020_field_franchise_id_eq(db_session: Session) -> None:
    fate = make_franchise(db_session, "Fate")
    make_anime(db_session, "Fate/Zero", franchise=fate)
    make_anime(db_session, "Standalone")

    where = [{"field": "franchise_id", "eq": "$franchise"}]

    assert answers(db_session, where, {"franchise": fate.id}) == {"Fate/Zero"}


# --- airing_between, currently airing, ran_for --------------------------------


def test_f020_airing_between(db_session: Session) -> None:
    make_anime(db_session, "Long-runner", start_year=1996, end_year=2012)
    make_anime(db_session, "Still airing", start_year=1999, end_year=None)
    make_anime(db_session, "Within", start_year=2005)
    make_anime(db_session, "Too early", start_year=1995, end_year=1999)
    make_anime(db_session, "Too late", start_year=2010)
    make_anime(db_session, "Later and still airing", start_year=2015, end_year=None)
    make_anime(db_session, "Unannounced", start_year=None, end_year=None)

    where = [{"airing_between": ["$from", "$to"]}]

    assert answers(db_session, where, {"from": 2000, "to": 2009}) == {
        "Long-runner",
        "Still airing",
        "Within",
    }
    assert answers(db_session, where, {"from": 1999, "to": 1999}) == {
        "Long-runner",
        "Still airing",
        "Too early",
    }


def test_f020_currently_airing_excludes_finished_and_not_yet_started(db_session: Session) -> None:
    make_anime(db_session, "Still airing", start_year=2024, end_year=None)
    make_anime(db_session, "Finished", start_year=2024, end_year=2025)
    make_anime(db_session, "Not started", start_year=2027, end_year=None)

    where = [
        {"field": "end_year", "is_null": True},
        {"field": "start_year", "lte": "$year"},
    ]

    assert answers(db_session, where, {"year": 2026}) == {"Still airing"}


def test_f020_ran_for(db_session: Session) -> None:
    make_anime(db_session, "Finished long-runner", start_year=2002, end_year=2007)
    make_anime(db_session, "Still airing", start_year=2021, end_year=None)
    make_anime(db_session, "Too short", start_year=2002, end_year=2006)
    make_anime(db_session, "Still airing but new", start_year=2022, end_year=None)
    make_anime(db_session, "Unannounced", start_year=None, end_year=None)

    where = [{"ran_for": "$years", "as_of": "$year"}]

    assert answers(db_session, where, {"years": 5, "year": 2026}) == {
        "Finished long-runner",
        "Still airing",
    }


# --- top ----------------------------------------------------------------------


def test_f020_top_by_popularity_with_a_tie_at_the_cutoff(db_session: Session) -> None:
    make_anime(db_session, "First", popularity=400)
    make_anime(db_session, "Tied, lower id", popularity=300)
    make_anime(db_session, "Tied, higher id", popularity=300)
    make_anime(db_session, "Last", popularity=100)

    where = [{"top": "$n", "by": "popularity"}]

    assert answers(db_session, where, {"n": 2}) == {"First", "Tied, lower id"}
    assert answers(db_session, where, {"n": 3}) == {"First", "Tied, lower id", "Tied, higher id"}


def test_f020_top_by_score_breaks_ties_by_popularity_then_id(db_session: Session) -> None:
    make_anime(db_session, "Best", score=90, popularity=10)
    make_anime(db_session, "Tied, less popular", score=85, popularity=20)
    make_anime(db_session, "Tied, more popular", score=85, popularity=30)
    make_anime(db_session, "Tied, more popular, higher id", score=85, popularity=30)
    # No score means no rank, however popular.
    make_anime(db_session, "Unscored", score=None, popularity=9999)

    where = [{"top": "$n", "by": "score"}]

    assert answers(db_session, where, {"n": 2}) == {"Best", "Tied, more popular"}
    assert answers(db_session, where, {"n": 10}) == {
        "Best",
        "Tied, less popular",
        "Tied, more popular",
        "Tied, more popular, higher id",
    }


def test_f020_top_with_character_answers_ranks_characters_only(db_session: Session) -> None:
    anime = make_anime(db_session, "One Piece", popularity=9999)
    make_character(db_session, "Luffy", popularity=50, appears_in=[anime])
    make_character(db_session, "Zoro", popularity=40, appears_in=[anime])
    make_character(db_session, "Buggy", popularity=5, appears_in=[anime])

    where = [{"top": 2, "by": "popularity"}]

    assert answers(db_session, where, answer_kind="character") == {"Luffy", "Zoro"}


def test_f020_top_ranks_everything_first_and_other_conditions_filter(db_session: Session) -> None:
    make_anime(db_session, "Action #1", popularity=300, genres=["Action"])
    make_anime(db_session, "Comedy #2", popularity=200, genres=["Comedy"])
    make_anime(db_session, "Action #3", popularity=100, genres=["Action"])

    where = [{"top": 2, "by": "popularity"}, {"predicate": "genre", "value": "Action"}]

    assert answers(db_session, where) == {"Action #1"}


# --- top within ---------------------------------------------------------------

TOP_IN_GENRE = {
    "top": "$n",
    "by": "popularity",
    "within": [{"predicate": "genre", "value": "$genre"}],
}


def test_f020_top_within_gives_no_rank_to_entities_outside(db_session: Session) -> None:
    make_anime(db_session, "Popular comedy", popularity=9999, genres=["Comedy"])
    make_anime(db_session, "Horror #1", popularity=300, genres=["Horror"])
    make_anime(db_session, "Horror #2", popularity=200, genres=["Horror"])
    make_anime(db_session, "Horror #3", popularity=100, genres=["Horror"])

    assert answers(db_session, [TOP_IN_GENRE], {"n": 2, "genre": "Horror"}) == {
        "Horror #1",
        "Horror #2",
    }


def test_f020_top_within_with_a_tie_at_the_cutoff(db_session: Session) -> None:
    make_anime(db_session, "Horror #1", popularity=300, genres=["Horror"])
    make_anime(db_session, "Tied, lower id", popularity=200, genres=["Horror"])
    make_anime(db_session, "Tied, higher id", popularity=200, genres=["Horror"])

    assert answers(db_session, [TOP_IN_GENRE], {"n": 2, "genre": "Horror"}) == {
        "Horror #1",
        "Tied, lower id",
    }


def test_f020_top_within_fewer_than_n_makes_all_of_them_answers(db_session: Session) -> None:
    make_anime(db_session, "Horror #1", popularity=300, genres=["Horror"])
    make_anime(db_session, "Horror #2", popularity=200, genres=["Horror"])
    make_anime(db_session, "Comedy", popularity=100, genres=["Comedy"])

    assert answers(db_session, [TOP_IN_GENRE], {"n": 25, "genre": "Horror"}) == {
        "Horror #1",
        "Horror #2",
    }


def test_f020_top_within_then_an_outside_condition_filters_the_ranked_result(
    db_session: Session,
) -> None:
    make_anime(db_session, "Horror movie #1", popularity=300, genres=["Horror"], format="MOVIE")
    make_anime(db_session, "Horror show #2", popularity=200, genres=["Horror"])
    make_anime(db_session, "Horror movie #3", popularity=100, genres=["Horror"], format="MOVIE")

    where = [TOP_IN_GENRE, {"predicate": "format", "value": "MOVIE"}]

    assert answers(db_session, where, {"n": 2, "genre": "Horror"}) == {"Horror movie #1"}


def test_f020_top_within_airing_between_ranks_by_score_inside_the_range(
    db_session: Session,
) -> None:
    make_anime(db_session, "90s best", start_year=1995, score=90)
    make_anime(db_session, "00s best", start_year=2004, score=85)
    make_anime(db_session, "00s second", start_year=2006, score=80)
    make_anime(db_session, "00s third", start_year=2008, score=75)

    where = [{"top": 2, "by": "score", "within": [{"airing_between": ["$from", "$to"]}]}]

    assert answers(db_session, where, {"from": 2000, "to": 2009}) == {"00s best", "00s second"}


# --- object_where -------------------------------------------------------------


def test_f020_object_where_tests_the_object_of_the_fact(db_session: Session) -> None:
    movie = make_anime(db_session, "Akira", format="MOVIE", start_year=1988)
    show = make_anime(db_session, "Cowboy Bebop", start_year=1998)
    make_character(db_session, "Kaneda", appears_in=[movie])
    make_character(db_session, "Spike", appears_in=[show])
    make_character(db_session, "Nobody")

    where = [
        {
            "predicate": "appears_in",
            "object_where": [
                {"predicate": "format", "value": "MOVIE"},
                {"field": "start_year", "lte": 1990},
            ],
        }
    ]

    assert answers(db_session, where, answer_kind="character") == {"Kaneda"}


# --- franchise answers --------------------------------------------------------


def test_f020_a_franchise_whose_studio_changed_between_seasons(db_session: Session) -> None:
    wit = make_studio(db_session, "Wit Studio")
    mappa = make_studio(db_session, "MAPPA")
    franchise = make_franchise(db_session, "Attack on Titan")
    make_anime(db_session, "Attack on Titan", franchise=franchise, studios=[wit])
    make_anime(db_session, "Attack on Titan Season 2", franchise=franchise, studios=[wit])
    make_anime(db_session, "Attack on Titan Final Season", franchise=franchise, studios=[mappa])

    where = [{"predicate": "produced_by", "object": "$studio"}]

    # One answer per franchise, for both studios.
    for studio in (wit, mappa):
        statement = answer_select("franchise", {"where": where}, {"studio": studio.id})
        assert [entity.id for entity in db_session.scalars(statement)] == [franchise.id]

    # Each season is its own answer, and only the matching ones.
    assert answers(db_session, where, {"studio": wit.id}) == {
        "Attack on Titan",
        "Attack on Titan Season 2",
    }
    assert answers(db_session, where, {"studio": mappa.id}) == {"Attack on Titan Final Season"}


def test_f020_franchise_conditions_must_all_hold_for_the_same_member(db_session: Session) -> None:
    bones = make_studio(db_session, "Bones")
    madhouse = make_studio(db_session, "Madhouse")
    one_member = make_franchise(db_session, "Movie by Bones")
    make_anime(db_session, "Bones movie", franchise=one_member, studios=[bones], format="MOVIE")
    split = make_franchise(db_session, "Split")
    make_anime(db_session, "Bones show", franchise=split, studios=[bones])
    make_anime(db_session, "Madhouse movie", franchise=split, studios=[madhouse], format="MOVIE")

    where = [
        {"predicate": "produced_by", "object": "$studio"},
        {"predicate": "format", "value": "MOVIE"},
    ]

    assert answers(db_session, where, {"studio": bones.id}, answer_kind="franchise") == {
        "Movie by Bones"
    }


def test_f020_min_members_at_the_cutoff(db_session: Session) -> None:
    three = make_franchise(db_session, "Three members")
    for number, format in enumerate(["TV", "MOVIE", "OVA"]):
        make_anime(db_session, f"Three {number}", franchise=three, format=format)
    two = make_franchise(db_session, "Two members")
    for number in range(2):
        make_anime(db_session, f"Two {number}", franchise=two)

    where = [{"min_members": "$n"}]

    assert answers(db_session, where, {"n": 3}, answer_kind="franchise") == {"Three members"}
    assert answers(db_session, where, {"n": 2}, answer_kind="franchise") == {
        "Three members",
        "Two members",
    }


def test_f020_min_members_counts_the_whole_franchise_beside_member_conditions(
    db_session: Session,
) -> None:
    big = make_franchise(db_session, "Big with a movie")
    make_anime(db_session, "Big show", franchise=big)
    make_anime(db_session, "Big movie", franchise=big, format="MOVIE")
    small = make_franchise(db_session, "Small with a movie")
    make_anime(db_session, "Small movie", franchise=small, format="MOVIE")
    shows = make_franchise(db_session, "Big without a movie")
    make_anime(db_session, "Show 1", franchise=shows)
    make_anime(db_session, "Show 2", franchise=shows)

    where = [{"min_members": 2}, {"predicate": "format", "value": "MOVIE"}]

    assert answers(db_session, where, answer_kind="franchise") == {"Big with a movie"}


# --- errors -------------------------------------------------------------------

GENRE = {"predicate": "genre", "value": "Action"}
TOP = {"top": 10, "by": "popularity"}
MIN_MEMBERS = {"min_members": 3}
NESTED = {"predicate": "appears_in", "object_where": [GENRE]}


@pytest.mark.parametrize(
    ("answer_kind", "where", "message"),
    [
        # Unknown condition type, predicate, field or operator.
        ("anime", [{"released_on": "Blu-ray"}], "unknown condition type"),
        ("anime", [{"predicate": "genre"}], "unknown condition type"),
        ("anime", [{"predicate": "genre", "value": "Action", "extra": 1}], "unknown condition"),
        ("anime", [{"airing_between": [2000, 2009], "extra": 1}], "unknown condition type"),
        ("anime", [{"top": 10}], "unknown condition type"),
        ("anime", ["genre"], "must be an object"),
        ("anime", [{"predicate": "directed_by", "object": 1}], "unknown predicate 'directed_by'"),
        ("anime", [{"field": "mal_id", "eq": 1}], "unknown field 'mal_id'"),
        ("anime", [{"field": "score", "gt": 80}], "unknown operator 'gt'"),
        ("anime", [{"field": "score"}], "exactly one operator"),
        ("anime", [{"field": "score", "gte": 80, "lte": 90}], "exactly one operator"),
        ("anime", [{"field": "franchise_id", "gte": 1}], "'franchise_id' takes 'eq' only"),
        ("anime", [{"top": 10, "by": "episodes"}], "unknown ranking 'episodes'"),
        # A predicate used with the wrong kind of right-hand side.
        ("anime", [{"predicate": "genre", "object": 1}], "takes a value"),
        ("anime", [{"predicate": "produced_by", "value": "Bones"}], "takes an object"),
        ("character", [{"predicate": "genre", "object_where": [GENRE]}], "takes a value"),
        # Badly typed operands.
        ("anime", [{"field": "score", "gte": "high"}], "must be an integer"),
        ("anime", [{"field": "score", "is_null": 1}], "must be true or false"),
        ("anime", [{"airing_between": [2000]}], "pair"),
        ("anime", [{"predicate": "genre", "value": 7}], "must be a string"),
        # Nesting that is not allowed.
        ("character", [{"predicate": "appears_in", "object_where": [TOP]}], "inside object_where"),
        (
            "character",
            [{"predicate": "appears_in", "object_where": [MIN_MEMBERS]}],
            "inside object_where",
        ),
        (
            "character",
            [{"predicate": "appears_in", "object_where": [NESTED]}],
            "inside object_where",
        ),
        ("anime", [{"top": 10, "by": "score", "within": [TOP]}], "inside within"),
        ("anime", [{"top": 10, "by": "score", "within": [MIN_MEMBERS]}], "inside within"),
        # min_members needs franchise answers.
        ("anime", [MIN_MEMBERS], "answer_kind is 'franchise'"),
        ("character", [MIN_MEMBERS], "answer_kind is 'franchise'"),
        # Not specified for franchises, so rejected rather than guessed at.
        ("franchise", [TOP], "top is not supported"),
        ("staff", [GENRE], "unknown answer_kind 'staff'"),
    ],
)
def test_f020_invalid_query_defs_raise_a_clear_error(
    answer_kind: str, where: list[Any], message: str
) -> None:
    with pytest.raises(QueryDefError, match=message):
        answer_select(answer_kind, {"where": where}, {})


@pytest.mark.parametrize("query_def", [{}, {"where": GENRE}, {"where": "genre"}, []])
def test_f020_a_query_def_needs_a_where_list(query_def: Any) -> None:
    with pytest.raises(QueryDefError, match="where"):
        answer_select("anime", query_def, {})


def test_f020_object_where_may_sit_inside_within(db_session: Session) -> None:
    bones_show = make_anime(db_session, "Bones show", studios=[make_studio(db_session, "Bones")])
    other_show = make_anime(db_session, "Other show")
    make_character(db_session, "Popular elsewhere", popularity=999, appears_in=[other_show])
    make_character(db_session, "Bones #1", popularity=50, appears_in=[bones_show])
    make_character(db_session, "Bones #2", popularity=40, appears_in=[bones_show])

    where = [
        {
            "top": 1,
            "by": "popularity",
            "within": [
                {
                    "predicate": "appears_in",
                    "object_where": [{"predicate": "format", "value": "TV"}],
                },
                {
                    "predicate": "appears_in",
                    "object_where": [{"field": "start_year", "eq": 2010}],
                },
            ],
        }
    ]

    assert answers(db_session, where, answer_kind="character") == {"Popular elsewhere"}
