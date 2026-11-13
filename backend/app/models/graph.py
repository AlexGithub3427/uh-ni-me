"""The knowledge graph: entities, the names players type for them, and facts."""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, check_in, identity_pk

ENTITY_KINDS = ("anime", "character", "studio", "franchise")


class Entity(Base):
    """An anime, character, studio or franchise."""

    __tablename__ = "entity"

    id: Mapped[int] = identity_pk()
    kind: Mapped[str]
    canonical_name: Mapped[str]
    popularity: Mapped[int]
    # Anime only. A NULL end_year means still airing.
    start_year: Mapped[int | None]
    end_year: Mapped[int | None]
    score: Mapped[int | None]
    episodes: Mapped[int | None]
    anilist_id: Mapped[int | None]
    mal_id: Mapped[int | None]
    wikidata_id: Mapped[str | None]
    # Anime only: the franchise entity it belongs to. The database does not
    # check the target's kind; ingest tests do (F-011).
    franchise_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="RESTRICT")
    )

    __table_args__ = (
        check_in("kind", ENTITY_KINDS),
        CheckConstraint(
            "(start_year IS NULL AND end_year IS NULL AND score IS NULL AND episodes IS NULL) "
            "OR kind = 'anime'",
            name="anime_only_fields",
        ),
        CheckConstraint(
            "end_year IS NULL OR (start_year IS NOT NULL AND end_year >= start_year)",
            name="year_order",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("franchise_id IS NULL OR kind = 'anime'", name="franchise_anime_only"),
        UniqueConstraint("kind", "anilist_id"),
        Index("ix_entity_franchise_id", "franchise_id"),
    )


class EntityAlias(Base):
    """A name a player might type. ``normalized`` is the match key."""

    __tablename__ = "entity_alias"

    id: Mapped[int] = identity_pk()
    entity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entity.id", ondelete="CASCADE"))
    alias: Mapped[str]
    normalized: Mapped[str]

    __table_args__ = (
        CheckConstraint("normalized <> ''", name="normalized_not_empty"),
        UniqueConstraint("entity_id", "normalized"),
        Index(
            "ix_entity_alias_normalized_trgm",
            "normalized",
            postgresql_using="gin",
            postgresql_ops={"normalized": "gin_trgm_ops"},
        ),
    )


class Fact(Base):
    """``(subject, predicate, object | value, source)``, pointing from the answer outward.

    Uniqueness includes ``source``: each source owns its rows, so two sources
    may assert the same fact. Read facts as existence checks.
    """

    __tablename__ = "fact"

    id: Mapped[int] = identity_pk()
    subject_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entity.id", ondelete="CASCADE"))
    predicate: Mapped[str]
    object_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE")
    )
    value: Mapped[str | None]
    source: Mapped[str]

    __table_args__ = (
        CheckConstraint("num_nonnulls(object_id, value) = 1", name="object_xor_value"),
        Index(
            "uq_fact_object_per_source",
            "subject_id",
            "predicate",
            "object_id",
            "source",
            unique=True,
            postgresql_where=text("object_id IS NOT NULL"),
        ),
        Index(
            "uq_fact_value_per_source",
            "subject_id",
            "predicate",
            "value",
            "source",
            unique=True,
            postgresql_where=text("value IS NOT NULL"),
        ),
        Index("ix_fact_predicate_object_id", "predicate", "object_id"),
        Index("ix_fact_predicate_value", "predicate", "value"),
    )
