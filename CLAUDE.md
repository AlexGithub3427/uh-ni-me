# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repo. Read this before making changes.

## Project in one paragraph

UH-NI-ME is a daily anime trivia game. Each day has 7 open-ended prompts ("Name an anime by MAPPA"), and rarer valid answers score more. A nightly Python batch ingests anime data from public APIs into Postgres as a knowledge graph. A FastAPI backend serves the daily puzzle and matches and scores answers. A Next.js + Tailwind frontend runs the game UI. The full plan is in `README.md`, and the feature specs are in `FEATURES.md`.

## Before you start a task

1. Find the feature in `FEATURES.md` and read its acceptance criteria. If the task isn't there, ask or add a spec first.
2. Keep changes scoped to that feature. Don't refactor unrelated code in the same change.
3. When a feature is done, update its status in `FEATURES.md`.

## Repo layout

- `frontend/`: Next.js (App Router) + TypeScript + Tailwind CSS
- `backend/app/`: FastAPI app (`api/` routers, `models/` SQLAlchemy, `schemas/` Pydantic, `services/` business logic)
- `backend/ingest/`: one client module per data source, plus the normalizer
- `backend/jobs/`: scheduled jobs (daily prompt generation)
- `backend/migrations/`: Alembic migrations
- `backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version`: Python project, lockfile and pinned Python version (managed with uv)

## Python dependencies (uv)

The backend uses [uv](https://docs.astral.sh/uv/) for Python versions, virtualenvs and dependencies. Don't use pip, venv, poetry or `requirements.txt`.

- Run every uv command from `backend/`. uv creates and manages `backend/.venv`, so you never need to activate it. Prefix commands with `uv run` instead.
- Add dependencies with `uv add <pkg>` (runtime) or `uv add --dev <pkg>` (tools like ruff and pytest). Don't hand-edit dependency lists in `pyproject.toml`.
- Commit `pyproject.toml` and `uv.lock` together. Never commit `.venv/`.
- The backend is an application, not an installable package (`[tool.uv] package = false`). Modules such as `app`, `ingest` and `jobs` are run from `backend/` as top-level packages.

## Commands

```bash
# backend (from backend/)
uv sync                                   # create/update .venv from uv.lock
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "msg" && uv run alembic upgrade head
uv run python -m ingest.run --source anilist --limit 100
uv run python -m jobs.generate_daily --date YYYY-MM-DD

# frontend (from frontend/)
npm run dev
npm run lint
npm run build
```

Run the relevant tests and linters before you call a task done.

## Core domain model

Everything is a small knowledge graph. Don't add one-off tables for new question types.

- `entity`: anime, character, staff or studio (`kind`, `canonical_name`, `popularity`, `source_ids` JSONB, `franchise_id`)
- `entity_alias`: every name a player might type; `normalized` is the match key
- `fact`: `(subject_id, predicate, object_id | value)`, e.g. `(Mob Psycho 100, produced_by, Bones)`
- `prompt_template` → `prompt` → `prompt_answer` (precomputed valid answers with `base_rarity`, `times_answered`)
- `daily_puzzle`: date → 7 ordered prompts
- `player`, `submission`

A new question type is a new `prompt_template` with a `query_def` over `fact`. If it needs a new predicate, add that to the ingest normalizer.

## Rules that matter

### Answer matching
- Always match against the prompt's precomputed `prompt_answer` set, never the whole `entity` table.
- Use one normalization function for both stored aliases and user input: lowercase, NFKC, strip punctuation and whitespace, and fold macrons (ō→o, ou→o). It lives in `backend/app/services/normalize.py`. Don't duplicate it.
- Try an exact alias match first, then `pg_trgm` similarity above a threshold set in config. Every threshold change needs a test case.
- Franchise handling: a prompt either accepts any entry of a franchise or requires a specific entry, as set by the template. Don't hardcode franchise behavior.

### Scoring
- Rarity scoring lives only in `backend/app/services/scoring.py`. Keep it a pure function of its inputs so it's easy to unit test.
- Rarity starts from `base_rarity` (popularity) and blends in `times_answered` as data grows. Document any formula change in `FEATURES.md`.

### Game integrity
- The server owns the timer: record when each prompt was served and reject answers after 25s plus a small grace period.
- Never send a prompt's answer list to the client before that prompt is finished.
- A player can submit only one answer per prompt per day.

### Data ingestion
- Use official or public APIs only (AniList GraphQL, MAL API v2, Wikidata SPARQL / MediaWiki API, anime-offline-database). No HTML scraping, and nothing from Anime-Planet or IMDb pages.
- Respect rate limits: back off on 429s, cache raw responses under `backend/.cache/`, and send a descriptive User-Agent.
- Ingest must be idempotent. Re-running upserts by `source_ids` and must not create duplicates.
- Never call external APIs from request handlers. The live game reads only from Postgres.

### Code style
- **Python:** type hints everywhere, Pydantic for I/O, `ruff` for lint and format, `pytest` for tests. Async SQLAlchemy in the API.
- **TypeScript:** strict mode, functional components, server components by default, `"use client"` only where needed (timer, input).
- **Tailwind:** utility classes inline. Extract a component rather than writing custom CSS. Keep design tokens in `tailwind.config`.
- API responses use snake_case on the backend. The frontend API client in `frontend/lib/api.ts` maps them to camelCase.

### Secrets and config
- All config comes from env vars (see `.env.example`). Never commit `.env`, API keys or cached API dumps.

## Testing expectations

- The matcher and scorer need unit tests with real-world anime naming cases: romaji vs English, "Shingeki no Kyojin" vs "Attack on Titan", typos, sequels.
- Every API endpoint needs at least one happy-path test and one rejection test.
- Ingest clients are tested against saved fixture responses in `backend/tests/fixtures/`, never live APIs.

## When unsure

Prefer the simplest thing that satisfies the acceptance criteria in `FEATURES.md`, and leave a `TODO(feature-id):` comment for follow-ups instead of building ahead.