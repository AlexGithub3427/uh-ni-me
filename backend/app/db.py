"""The API's async database session (asyncpg). Batch scripts use sync sessions instead."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().async_database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Handlers commit their own writes."""
    async with _session_factory()() as session:
        yield session
