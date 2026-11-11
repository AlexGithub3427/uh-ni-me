from pathlib import Path

import pytest

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _env_example_defaults() -> dict[str, str]:
    """Parse the uncommented KEY=value lines of .env.example."""
    defaults: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        defaults[key] = value
    return defaults


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every documented config var so only code defaults apply."""
    for key in _env_example_defaults():
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_f001_settings_defaults_match_env_example(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)
    example = _env_example_defaults()

    assert example, ".env.example has no config vars"
    for key, raw in example.items():
        field = key.lower()
        assert field in Settings.model_fields, f"{key} is in .env.example but not in Settings"
        assert str(getattr(settings, field)) == raw, f"default for {key} differs from .env.example"


def test_f001_every_setting_is_listed_in_env_example() -> None:
    documented = {key.lower() for key in _env_example_defaults()}

    assert set(Settings.model_fields) == documented


def test_f001_settings_read_env_vars(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANSWER_GRACE_SECONDS", "5")
    clean_env.setenv("MATCH_SIMILARITY_THRESHOLD", "0.55")

    settings = Settings(_env_file=None)

    assert settings.answer_grace_seconds == 5
    assert settings.match_similarity_threshold == 0.55


def test_f001_settings_reject_invalid_values(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANSWER_TIME_LIMIT_SECONDS", "soon")

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_f001_database_urls_pick_the_driver(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert settings.async_database_url == "postgresql+asyncpg://uhnime:uhnime@localhost:5432/uhnime"
    assert settings.sync_database_url == "postgresql+psycopg://uhnime:uhnime@localhost:5432/uhnime"
    assert settings.sync_test_database_url == (
        "postgresql+psycopg://uhnime:uhnime@localhost:5432/uhnime_test"
    )
