"""Shared fixtures: a migrated test database and a per-test rolled-back session."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings

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
    # TODO(F-030): API tests need an async session bound to this same transaction.
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
