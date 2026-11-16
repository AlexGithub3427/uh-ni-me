"""Matching a player's guess against one prompt's precomputed answers (F-032)."""

from sqlalchemy import REAL, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, EntityAlias, PromptAnswer
from app.services.normalize import normalize


async def match_answer(
    session: AsyncSession, prompt_id: int, text: str, *, threshold: float
) -> Entity | None:
    """The answer of ``prompt_id`` that ``text`` names, or None for a wrong guess.

    An exact alias match wins. Otherwise the alias most similar to the guess
    wins, if its ``pg_trgm`` similarity is above ``threshold``. Answers that
    match equally well are settled by popularity. Only the prompt's own
    answers are candidates, and franchise answers need no special handling:
    a franchise entity carries its members' aliases.
    """
    key = normalize(text)
    if not key:
        return None
    candidates = (
        select(Entity)
        .join(PromptAnswer, PromptAnswer.entity_id == Entity.id)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(PromptAnswer.prompt_id == prompt_id)
    )
    most_popular = (Entity.popularity.desc(), Entity.id)

    exact = await session.scalar(
        candidates.where(EntityAlias.normalized == key).order_by(*most_popular).limit(1)
    )
    if exact is not None:
        return exact

    similarity = func.similarity(EntityAlias.normalized, key)
    # similarity() returns a real. Compared with a double, a similarity of
    # exactly 0.4 would count as above a 0.4 threshold.
    return await session.scalar(
        candidates.where(similarity > cast(threshold, REAL))
        .order_by(similarity.desc(), *most_popular)
        .limit(1)
    )
