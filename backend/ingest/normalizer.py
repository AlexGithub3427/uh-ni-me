"""Normalizer: AniList source records → the knowledge graph (F-011, F-015).

Turns the records fetched by ``ingest.anilist`` into ``entity``, ``entity_alias``
and ``fact`` rows. Running it again upserts: entities are keyed by
``(kind, anilist_id)`` and facts are replaced per subject and source.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy import and_, delete, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Entity, EntityAlias, Fact
from app.services.normalize import normalize
from ingest.anilist import AniListAnime, AniListCharacter, AniListStudio, AniListTag

SOURCE = "anilist"

# Relations that make two anime part of one franchise. Adaptations, spin-offs,
# alternative versions and character crossovers do not.
FRANCHISE_RELATIONS = frozenset({"SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY"})

# Statuses without an end yet. Everything else (FINISHED, CANCELLED) has ended.
UNFINISHED_STATUSES = frozenset({"RELEASING", "HIATUS", "NOT_YET_RELEASED"})

# Rows per INSERT, to stay well under Postgres's 65535 bind parameters.
_CHUNK_SIZE = 1000

# (subject, predicate, object | value) with entities as (kind, anilist_id).
_EntityKey = tuple[str, int]
_FactKey = tuple[_EntityKey, str, _EntityKey | None, str | None]


def upsert_anilist(
    session: Session, records: Sequence[AniListAnime], *, tag_min_rank: int | None = None
) -> None:
    """Upsert the entities, aliases and facts for ``records``. The caller commits.

    ``tag_min_rank`` defaults to the ``TAG_MIN_RANK`` setting.
    """
    if tag_min_rank is None:
        tag_min_rank = get_settings().tag_min_rank
    anime = {record.id: record for record in records if _anime_names(record)}
    studios: dict[int, AniListStudio] = {}
    characters: dict[int, AniListCharacter] = {}
    facts: set[_FactKey] = set()

    for record in anime.values():
        subject = ("anime", record.id)
        if record.format:
            facts.add((subject, "format", None, record.format))
        for genre in record.genres:
            facts.add((subject, "genre", None, genre))
        for tag in record.tags:
            if _tag_applies(tag, tag_min_rank):
                facts.add((subject, "tag", None, tag.name))
        if record.source:
            # Not named "source": fact.source already means the data source.
            facts.add((subject, "source_material", None, record.source))
        for studio in record.studios:
            # AniList also lists licensors and publishers; they did not make the anime.
            if studio.is_animation_studio:
                studios[studio.id] = studio
                facts.add((subject, "produced_by", ("studio", studio.id), None))
        for character in record.characters:
            if _character_names(character):
                characters[character.id] = character
                facts.add((("character", character.id), "appears_in", subject, None))

    names: dict[_EntityKey, list[str]] = {}
    franchise_rows: list[dict[str, Any]] = []
    root_of: dict[int, int] = {}
    for members in _franchise_groups(anime.values()):
        # TODO(F-011): if a later ingest finds an earlier root, the franchise is
        # re-keyed: its answer history is lost and the old row is left orphaned.
        root = min(members, key=_root_order)
        root_of.update({member.id: root.id for member in members})
        franchise_rows.append(
            {
                "kind": "franchise",
                "anilist_id": root.id,
                "canonical_name": _anime_names(root)[0],
                "popularity": max(member.popularity or 0 for member in members),
            }
        )
        root_first = [root, *(member for member in members if member is not root)]
        names["franchise", root.id] = [n for member in root_first for n in _anime_names(member)]
    entity_ids = _upsert_entities(session, franchise_rows)

    anime_rows = []
    for record in anime.values():
        start_year, end_year = _years(record)
        names["anime", record.id] = _anime_names(record)
        anime_rows.append(
            {
                "kind": "anime",
                "anilist_id": record.id,
                "canonical_name": _anime_names(record)[0],
                "popularity": record.popularity or 0,
                "start_year": start_year,
                "end_year": end_year,
                "score": record.average_score,
                "episodes": record.episodes,
                "franchise_id": entity_ids["franchise", root_of[record.id]],
            }
        )
    entity_ids |= _upsert_entities(session, anime_rows)

    for studio in studios.values():
        names["studio", studio.id] = [studio.name]
    for character in characters.values():
        names["character", character.id] = _character_names(character)
    entity_ids |= _upsert_entities(
        session,
        [
            {
                "kind": kind,
                "anilist_id": source.id,
                "canonical_name": names[kind, source.id][0],
                "popularity": source.favourites or 0,
            }
            for kind, sources in (("studio", studios), ("character", characters))
            for source in sources.values()
        ],
    )

    _add_aliases(session, {entity_ids[key]: entity_names for key, entity_names in names.items()})
    _replace_facts(session, [entity_ids["anime", id] for id in anime], facts, entity_ids)


# --- Source records → values ---------------------------------------------------


def _usable(names: Iterable[str | None]) -> list[str]:
    """Names with a match key, in order, without repeats of the same key."""
    seen: set[str] = set()
    usable = []
    for name in names:
        key = normalize(name) if name else ""
        if key and key not in seen:
            seen.add(key)
            usable.append(name.strip())
    return usable


def _anime_names(record: AniListAnime) -> list[str]:
    """Every title variant. The first one is the canonical name."""
    title = record.title
    return _usable([title.english, title.romaji, title.native, *record.synonyms])


def _character_names(character: AniListCharacter) -> list[str]:
    name = character.name
    return _usable([name.full, name.native, *name.alternative])


def _tag_applies(tag: AniListTag, min_rank: int) -> bool:
    """Ranked at least ``min_rank``, and neither a spoiler (in general or here) nor adult."""
    if tag.is_general_spoiler or tag.is_media_spoiler or tag.is_adult:
        return False
    return tag.rank is not None and tag.rank >= min_rank


def _years(record: AniListAnime) -> tuple[int | None, int | None]:
    """``(start_year, end_year)``. ``end_year`` is None only while the anime has not ended."""
    start_year = record.start_date.year
    if start_year is None or record.status in UNFINISHED_STATUSES:
        return start_year, None
    # A finished anime with no end date ended the year it started.
    return start_year, max(record.end_date.year or start_year, start_year)


def _franchise_groups(records: Iterable[AniListAnime]) -> list[list[AniListAnime]]:
    """Group anime connected by franchise relations (union-find).

    Relations may point at anime that were not fetched. Those still connect the
    fetched anime on either side of them, but are not members themselves.
    """
    parent: dict[int, int] = {}

    def find(id: int) -> int:
        parent.setdefault(id, id)
        while parent[id] != id:
            parent[id] = parent[parent[id]]
            id = parent[id]
        return id

    records = list(records)
    for record in records:
        for relation in record.relations:
            if relation.type == "ANIME" and relation.relation_type in FRANCHISE_RELATIONS:
                parent[find(relation.id)] = find(record.id)

    groups: defaultdict[int, list[AniListAnime]] = defaultdict(list)
    for record in records:
        groups[find(record.id)].append(record)
    return list(groups.values())


def _root_order(record: AniListAnime) -> tuple[bool, int, int]:
    """Earliest start year first (unknown years last), then lowest AniList id."""
    year = record.start_date.year
    return (year is None, year or 0, record.id)


# --- Writes --------------------------------------------------------------------


def _chunks[T](rows: Sequence[T]) -> Iterator[Sequence[T]]:
    for start in range(0, len(rows), _CHUNK_SIZE):
        yield rows[start : start + _CHUNK_SIZE]


def _upsert_entities(session: Session, rows: Sequence[dict[str, Any]]) -> dict[_EntityKey, int]:
    """Insert or update by ``(kind, anilist_id)``. Rows must all have the same columns.

    Returns the entity id for each ``(kind, anilist_id)``.
    """
    ids: dict[_EntityKey, int] = {}
    for chunk in _chunks(rows):
        statement = insert(Entity).values(chunk)
        updated = {
            column: statement.excluded[column]
            for column in chunk[0]
            if column not in ("kind", "anilist_id")
        }
        statement = statement.on_conflict_do_update(
            index_elements=[Entity.kind, Entity.anilist_id], set_=updated
        ).returning(Entity.kind, Entity.anilist_id, Entity.id)
        for kind, anilist_id, entity_id in session.execute(statement):
            ids[kind, anilist_id] = entity_id
    return ids


def _add_aliases(session: Session, names: Mapping[int, Sequence[str]]) -> None:
    """Add any alias an entity does not have yet.

    Aliases are never removed: the table has no ``source``, so a name that
    disappears from AniList cannot be told apart from one another source added.
    """
    rows = {
        (entity_id, normalize(name)): name
        for entity_id, entity_names in names.items()
        # Reversed so that the first name wins when two share a match key.
        for name in reversed(entity_names)
    }
    values = [
        {"entity_id": entity_id, "alias": name, "normalized": key}
        for (entity_id, key), name in rows.items()
    ]
    for chunk in _chunks(values):
        session.execute(
            insert(EntityAlias)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=[EntityAlias.entity_id, EntityAlias.normalized])
        )


def _replace_facts(
    session: Session,
    anime_ids: Sequence[int],
    facts: Iterable[_FactKey],
    entity_ids: Mapping[_EntityKey, int],
) -> None:
    """Replace this source's facts about ``anime_ids`` with ``facts``.

    An anime's record owns the facts it is the subject of and the ``appears_in``
    facts pointing at it. A character's facts about anime outside this run stay.
    """
    for chunk in _chunks(anime_ids):
        session.execute(
            delete(Fact).where(
                Fact.source == SOURCE,
                or_(
                    Fact.subject_id.in_(chunk),
                    and_(Fact.predicate == "appears_in", Fact.object_id.in_(chunk)),
                ),
            )
        )
    values = [
        {
            "subject_id": entity_ids[subject],
            "predicate": predicate,
            "object_id": entity_ids[obj] if obj else None,
            "value": value,
            "source": SOURCE,
        }
        for subject, predicate, obj, value in facts
    ]
    for chunk in _chunks(values):
        session.execute(insert(Fact).values(chunk))
