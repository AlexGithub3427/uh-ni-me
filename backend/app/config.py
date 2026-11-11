"""Application config. Every value comes from an env var listed in .env.example."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


def _with_driver(url: str, driver: str) -> str:
    """Turn a driverless ``postgresql://`` URL into ``postgresql+<driver>://``."""
    scheme, sep, rest = url.partition("://")
    return f"{scheme.split('+')[0]}+{driver}{sep}{rest}"


class Settings(BaseSettings):
    """Defaults must match .env.example (checked by tests/test_config.py)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Database
    database_url: str = "postgresql://uhnime:uhnime@localhost:5432/uhnime"
    test_database_url: str = "postgresql://uhnime:uhnime@localhost:5432/uhnime_test"

    # Ingest
    ingest_user_agent: str = "uh-ni-me/0.1 (+https://github.com/YOUR_USERNAME/uh-ni-me)"
    mal_client_id: str = ""

    # Answer matching
    match_similarity_threshold: float = 0.4

    # Game timer
    answer_time_limit_seconds: int = 25
    answer_grace_seconds: int = 2
    max_guesses_per_prompt: int = 20

    # Prompt generation
    prompt_min_answers: int = 25
    prompt_max_answers: int = 500
    prompt_repeat_window_days: int = 60
    puzzle_seed: str = "uh-ni-me"

    # Scoring
    scoring_blend_min_submissions: int = 50

    @property
    def async_database_url(self) -> str:
        """For the API (async SQLAlchemy + asyncpg)."""
        return _with_driver(self.database_url, "asyncpg")

    @property
    def sync_database_url(self) -> str:
        """For ingest, jobs and Alembic (sync SQLAlchemy + psycopg)."""
        return _with_driver(self.database_url, "psycopg")

    @property
    def sync_test_database_url(self) -> str:
        """For pytest only."""
        return _with_driver(self.test_database_url, "psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
