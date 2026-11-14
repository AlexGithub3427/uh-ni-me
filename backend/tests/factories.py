"""Builders for small knowledge graphs in tests (entities and their facts)."""

from collections.abc import Sequence
from types import EllipsisType
from typing import Any

from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.models import Entity, Fact


def _entity(session: Session, kind: str, name: str, **columns: Any) -> Entity:
    entity = Entity(kind=kind, canonical_name=name, **columns)
    session.add(entity)
    session.flush()
    return entity


def add_fact(
    session: Session,
    subject: Entity,
    predicate: str,
    *,
    object: Entity | None = None,
    value: str | None = None,
    source: str = "anilist",
) -> None:
    session.add(
        Fact(
            subject_id=subject.id,
            predicate=predicate,
            object_id=object.id if object else None,
            value=value,
            source=source,
        )
    )
    session.flush()


def make_studio(session: Session, name: str, *, popularity: int = 10) -> Entity:
    return _entity(session, "studio", name, popularity=popularity)


def make_franchise(session: Session, name: str, *, popularity: int = 100) -> Entity:
    return _entity(session, "franchise", name, popularity=popularity)


def make_anime(
    session: Session,
    name: str,
    *,
    popularity: int = 100,
    start_year: int | None = 2010,
    end_year: int | None | EllipsisType = ...,
    score: int | None = None,
    episodes: int | None = None,
    franchise: Entity | None = None,
    format: str | None = "TV",
    studios: Sequence[Entity] = (),
    genres: Sequence[str] = (),
    tags: Sequence[str] = (),
    source_material: str | None = None,
) -> Entity:
    """A TV anime that started and ended in 2010. ``end_year=None`` means still airing."""
    anime = _entity(
        session,
        "anime",
        name,
        popularity=popularity,
        start_year=start_year,
        end_year=start_year if end_year is ... else end_year,
        score=score,
        episodes=episodes,
        franchise_id=franchise.id if franchise else None,
    )
    if format:
        add_fact(session, anime, "format", value=format)
    for studio in studios:
        add_fact(session, anime, "produced_by", object=studio)
    for genre in genres:
        add_fact(session, anime, "genre", value=genre)
    for tag in tags:
        add_fact(session, anime, "tag", value=tag)
    if source_material:
        add_fact(session, anime, "source_material", value=source_material)
    return anime


def make_character(
    session: Session, name: str, *, popularity: int = 10, appears_in: Sequence[Entity] = ()
) -> Entity:
    character = _entity(session, "character", name, popularity=popularity)
    for anime in appears_in:
        add_fact(session, character, "appears_in", object=anime)
    return character


def names(session: Session, statement: Select[tuple[Entity]]) -> list[str]:
    """The canonical names a statement returns, in its order."""
    return [entity.canonical_name for entity in session.scalars(statement)]
