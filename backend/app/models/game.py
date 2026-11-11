"""Daily puzzles, players and their submissions."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, check_in, identity_pk

OUTCOMES = ("accepted", "expired")
# Most common to rarest. Points and cutoffs live in services/scoring.py (F-033).
RARITY_TIERS = ("larp", "normie", "niche", "weeb", "uh-ni-me")


class DailyPuzzle(Base):
    """One prompt of one UTC day's puzzle. Positions are 1-based."""

    __tablename__ = "daily_puzzle"

    day: Mapped[date] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompt.id", ondelete="RESTRICT"))

    __table_args__ = (
        CheckConstraint("position >= 1", name="position_min"),
        # Also the target of submission's (day, prompt_id) foreign key.
        UniqueConstraint("day", "prompt_id"),
        Index("ix_daily_puzzle_prompt_id_day", "prompt_id", "day"),
    )


class Player(Base):
    """An anonymous visitor. The id is the cookie value (F-034)."""

    __tablename__ = "player"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Submission(Base):
    """One row per player per prompt, created when the prompt is served."""

    __tablename__ = "submission"

    id: Mapped[int] = identity_pk()
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="RESTRICT"))
    day: Mapped[date]
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompt.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime]
    guess_count: Mapped[int] = mapped_column(server_default="0")
    wrong_guesses: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    finished_at: Mapped[datetime | None]
    raw_text: Mapped[str | None]  # the accepted input
    matched_entity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str | None]
    points: Mapped[int | None]
    rarity_tier: Mapped[str | None]

    __table_args__ = (
        # The prompt must be part of that day's puzzle.
        ForeignKeyConstraint(
            ["day", "prompt_id"],
            ["daily_puzzle.day", "daily_puzzle.prompt_id"],
            ondelete="RESTRICT",
        ),
        check_in("outcome", OUTCOMES),
        check_in("rarity_tier", RARITY_TIERS),
        CheckConstraint(
            "(outcome IS NULL) = (finished_at IS NULL)", name="outcome_finished_together"
        ),
        CheckConstraint(
            "(outcome IS NOT DISTINCT FROM 'accepted') = (matched_entity_id IS NOT NULL)",
            name="accepted_has_match",
        ),
        # Leading (player_id, day) serves "this player's progress today".
        UniqueConstraint("player_id", "day", "prompt_id"),
    )
