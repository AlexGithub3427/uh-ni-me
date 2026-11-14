"""Shared fixtures: a migrated test database and a per-test rolled-back session."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import _with_driver, get_settings
from app.db import get_session
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Alembic pointed at TEST_DATABASE_URL."""
    settings = get_settings()
    if settings.test_database_url == settings.database_url:
        pytest.exit("TEST_DATABASE_URL must not be the same database as DATABASE_URL")

    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.sync_test_database_url)
    return config


@pytest.fixture(scope="session")
def db_engine(alembic_config: Config) -> Iterator[Engine]:
    """Run ``alembic upgrade head`` once against TEST_DATABASE_URL."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(get_settings().sync_test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    The session joins the outer transaction through savepoints, so code under
    test may call ``commit()`` and still leave nothing behind.
    """
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


# --- API tests ---------------------------------------------------------------
# The API talks to Postgres through asyncpg, so its tests are async
# (``pytestmark = pytest.mark.anyio``) and use the two fixtures below in place
# of ``db_session``.


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def api_session(db_engine: Engine) -> AsyncIterator[AsyncSession]:
    """The async twin of ``db_session``: rolled back after the test.

    Seed data with the sync factories through ``await api_session.run_sync(fn)``.
    """
    url = _with_driver(get_settings().test_database_url, "asyncpg")
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def api_client(api_session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    """An HTTP client for the app whose requests all use ``api_session``."""
    app.dependency_overrides[get_session] = lambda: api_session
    transport = httpx2.ASGITransport(app=app)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
