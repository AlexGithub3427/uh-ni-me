"""SQLAlchemy models (F-002). Import from here so every table is registered."""

from app.models.base import Base
from app.models.game import OUTCOMES, RARITY_TIERS, DailyPuzzle, Player, Submission
from app.models.graph import ENTITY_KINDS, Entity, EntityAlias, Fact
from app.models.prompts import Prompt, PromptAnswer, PromptTemplate

__all__ = [
    "ENTITY_KINDS",
    "OUTCOMES",
    "RARITY_TIERS",
    "Base",
    "DailyPuzzle",
    "Entity",
    "EntityAlias",
    "Fact",
    "Player",
    "Prompt",
    "PromptAnswer",
    "PromptTemplate",
    "Submission",
]
