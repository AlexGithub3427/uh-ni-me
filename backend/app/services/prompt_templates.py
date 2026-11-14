"""The seeded prompt templates (F-020).

Each template is data: a text with ``{placeholders}``, an ``answer_kind`` and
the ``where`` list of its ``query_def``. The project owner writes the
templates; the list mirrors FEATURES.md and nothing here is invented.

Params: ``$name`` in a condition and ``{name}`` in the text both refer to a
prompt param. A param holding an entity (``studio``, ``anime``, ``franchise``)
is that entity's id. Some params exist only for the text or only for the query:
a decade prompt carries ``decade`` (for the text) plus ``from`` and ``to`` (for
the query), because a ``query_def`` has no arithmetic.

``choices`` lists the fixed param sets the spec gives a template, such as the
N of a "top N". Every other param (studios, genres, years, ...) comes from the
data when prompts are generated.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select

from app.models import Entity
from app.services.query_def import answer_select

Condition = dict[str, Any]


@dataclass(frozen=True)
class TemplateDef:
    slug: str
    text: str
    where: tuple[Condition, ...]
    answer_kind: str = "anime"
    choices: tuple[dict[str, Any], ...] = ()

    @property
    def query_def(self) -> dict[str, Any]:
        return {"where": list(self.where)}

    def answers(self, params: Mapping[str, Any]) -> Select[tuple[Entity]]:
        """A SELECT of this template's valid answers for ``params``."""
        return answer_select(self.answer_kind, self.query_def, params)


def _choices(name: str, *values: int) -> tuple[dict[str, Any], ...]:
    return tuple({name: value} for value in values)


# --- shared conditions --------------------------------------------------------

_BY_STUDIO: Condition = {"predicate": "produced_by", "object": "$studio"}
_GENRE: Condition = {"predicate": "genre", "value": "$genre"}
_MOVIE: Condition = {"predicate": "format", "value": "MOVIE"}
_IN_YEAR: Condition = {"airing_between": ["$year", "$year"]}
# Decade prompts carry from = the decade and to = the decade + 9.
_IN_DECADE: Condition = {"airing_between": ["$from", "$to"]}


def _appears_in(*conditions: Condition) -> Condition:
    """A character from an anime that satisfies ``conditions``."""
    return {"predicate": "appears_in", "object_where": list(conditions)}


TEMPLATES: tuple[TemplateDef, ...] = (
    # --- anime answers --------------------------------------------------------
    TemplateDef("anime-by-studio", "Name an anime by {studio}", (_BY_STUDIO,)),
    TemplateDef("anime-aired-in-year", "Name an anime that aired in {year}", (_IN_YEAR,)),
    TemplateDef(
        "anime-premiered-in-year",
        "Name an anime that premiered in {year}",
        ({"field": "start_year", "eq": "$year"},),
    ),
    TemplateDef(
        "anime-top-popular",
        "Name an anime in the top {n} most popular anime",
        ({"top": "$n", "by": "popularity"},),
        choices=_choices("n", 25, 50, 100, 250, 500),
    ),
    TemplateDef(
        "anime-top-rated",
        "Name an anime in the top {n} highest rated anime",
        ({"top": "$n", "by": "score"},),
        choices=_choices("n", 25, 50, 100, 250, 500),
    ),
    TemplateDef("anime-by-genre", "Name a {genre} anime", (_GENRE,)),
    TemplateDef(
        "anime-by-two-genres",
        "Name a {genre} and {genre2} anime",
        (_GENRE, {"predicate": "genre", "value": "$genre2"}),
    ),
    TemplateDef(
        "anime-by-genre-in-decade",
        "Name a {genre} anime airing in the {decade}s",
        (_GENRE, _IN_DECADE),
    ),
    TemplateDef(
        "anime-by-genre-and-studio", "Name a {genre} anime by {studio}", (_GENRE, _BY_STUDIO)
    ),
    TemplateDef(
        "anime-by-studio-in-decade",
        "Name an anime by {studio} from the {decade}s",
        (_BY_STUDIO, _IN_DECADE),
    ),
    TemplateDef(
        "anime-top-popular-in-genre",
        "Name an anime in the top {n} most popular {genre} anime",
        ({"top": "$n", "by": "popularity", "within": [_GENRE]},),
        choices=_choices("n", 25, 50, 100),
    ),
    TemplateDef(
        "anime-top-rated-in-decade",
        "Name an anime from the top {n} highest rated {decade}'s anime",
        ({"top": "$n", "by": "score", "within": [_IN_DECADE]},),
        choices=_choices("n", 25, 50, 100, 250),
    ),
    TemplateDef(
        "anime-movie-in-decade", "Name an anime movie from the {decade}s", (_MOVIE, _IN_DECADE)
    ),
    TemplateDef("anime-movie-by-genre", "Name a {genre} anime movie", (_GENRE, _MOVIE)),
    TemplateDef("anime-movie-by-studio", "Name an anime movie by {studio}", (_MOVIE, _BY_STUDIO)),
    TemplateDef(
        "anime-rated-at-least",
        "Name an anime rated {score}+",
        ({"field": "score", "gte": "$score"},),
        choices=_choices("score", 80, 85),
    ),
    TemplateDef(
        "anime-rated-below",
        "Name an anime rated below {score}",
        # Scores are whole numbers, so "below 60" is lte 59: max = score - 1.
        ({"field": "score", "lte": "$max"},),
        choices=({"score": 60, "max": 59}, {"score": 65, "max": 64}),
    ),
    TemplateDef(
        "anime-currently-airing",
        "Name an anime currently airing",
        # year = the year the prompt was generated. The second condition drops
        # anime that have not started yet, which also have no end_year.
        ({"field": "end_year", "is_null": True}, {"field": "start_year", "lte": "$year"}),
    ),
    TemplateDef(
        "anime-ran-for-years",
        "Name an anime that ran for {years}+ years",
        # year = the year the prompt was generated.
        ({"ran_for": "$years", "as_of": "$year"},),
        choices=_choices("years", 3, 5, 10),
    ),
    # --- franchise answers ----------------------------------------------------
    TemplateDef(
        "franchise-with-movie",
        "Name a franchise with an anime movie",
        (_MOVIE,),
        answer_kind="franchise",
    ),
    TemplateDef(
        "franchise-by-studio",
        "Name a franchise with an anime by {studio}",
        (_BY_STUDIO,),
        answer_kind="franchise",
    ),
    TemplateDef(
        "franchise-aired-in-decade",
        "Name a franchise with an anime that aired in the {decade}s",
        (_IN_DECADE,),
        answer_kind="franchise",
    ),
    TemplateDef(
        "franchise-with-min-anime",
        "Name a franchise with {n}+ anime",
        ({"min_members": "$n"},),
        answer_kind="franchise",
        choices=_choices("n", 3, 5, 10),
    ),
    # --- character answers ----------------------------------------------------
    TemplateDef(
        "character-from-anime",
        "Name a character from {anime}",
        ({"predicate": "appears_in", "object": "$anime"},),
        answer_kind="character",
    ),
    TemplateDef(
        "character-from-franchise",
        "Name a character from the {franchise} franchise",
        (_appears_in({"field": "franchise_id", "eq": "$franchise"}),),
        answer_kind="character",
    ),
    TemplateDef(
        "character-from-studio-anime",
        "Name a character from an anime by {studio}",
        (_appears_in(_BY_STUDIO),),
        answer_kind="character",
    ),
    TemplateDef(
        "character-from-anime-aired-in-year",
        "Name a character from an anime that aired in {year}",
        (_appears_in(_IN_YEAR),),
        answer_kind="character",
    ),
    TemplateDef(
        "character-top-favourited",
        "Name one of the top {n} most favourited characters",
        ({"top": "$n", "by": "popularity"},),
        answer_kind="character",
        choices=_choices("n", 25, 50, 100, 250),
    ),
    # --- anime answers that use the F-015 data --------------------------------
    TemplateDef("anime-by-tag", "Name a {tag} anime", ({"predicate": "tag", "value": "$tag"},)),
    TemplateDef(
        "anime-original",
        "Name an original anime",
        ({"predicate": "source_material", "value": "ORIGINAL"},),
    ),
    TemplateDef(
        "anime-adapted-from",
        "Name an anime adapted from a {source_label}",
        ({"predicate": "source_material", "value": "$source"},),
        choices=(
            {"source": "MANGA", "source_label": "manga"},
            {"source": "LIGHT_NOVEL", "source_label": "light novel"},
            {"source": "VIDEO_GAME", "source_label": "video game"},
            {"source": "VISUAL_NOVEL", "source_label": "visual novel"},
        ),
    ),
    TemplateDef(
        "anime-min-episodes",
        "Name an anime with {episodes}+ episodes",
        ({"field": "episodes", "gte": "$episodes"},),
        choices=_choices("episodes", 100, 200),
    ),
    TemplateDef(
        "tv-anime-13-or-fewer-episodes",
        "Name a TV anime with 13 or fewer episodes",
        # format = TV only: movies, OVAs, ONAs, specials and TV shorts are not answers.
        ({"predicate": "format", "value": "TV"}, {"field": "episodes", "lte": 13}),
    ),
)
