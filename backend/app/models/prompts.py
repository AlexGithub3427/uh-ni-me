"""Prompt templates, concrete prompts and their precomputed answers."""

from typing import Any

from sqlalchemy import REAL, BigInteger, CheckConstraint, ForeignKey, UniqueConstraint, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, check_in, identity_pk
from app.models.graph import ENTITY_KINDS


class PromptTemplate(Base):
    """A question shape, e.g. "Name an anime produced by {studio}"."""

    __tablename__ = "prompt_template"

    id: Mapped[int] = identity_pk()
    slug: Mapped[str] = mapped_column(unique=True)
    text: Mapped[str]
    answer_kind: Mapped[str]
    query_def: Mapped[dict[str, Any]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(server_default=true())

    __table_args__ = (check_in("answer_kind", ENTITY_KINDS),)


class Prompt(Base):
    """A template with its params filled in."""

    __tablename__ = "prompt"

    id: Mapped[int] = identity_pk()
    template_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prompt_template.id", ondelete="RESTRICT")
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    text: Mapped[str]
    active: Mapped[bool] = mapped_column(server_default=true())

    __table_args__ = (UniqueConstraint("template_id", "params"),)


class PromptAnswer(Base):
    """One valid answer for a prompt. The matcher only ever looks here."""

    __tablename__ = "prompt_answer"

    prompt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prompt.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True
    )
    base_rarity: Mapped[float] = mapped_column(REAL)
    times_answered: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (
        CheckConstraint("base_rarity BETWEEN 0 AND 1", name="base_rarity_range"),
        CheckConstraint("times_answered >= 0", name="times_answered_min"),
    )
