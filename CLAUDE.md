# CLAUDE.md

Guidance for AI coding assistants (and humans) working in this repo. Read this before making changes.

## Project in one paragraph

UH-NI-ME is a daily anime trivia game. Each day has 7 open-ended prompts ("Name an anime by MAPPA"), and rarer valid answers score more. A nightly Python batch ingests anime data from public APIs into Postgres as a knowledge graph. A FastAPI backend serves the daily puzzle and matches and scores answers. A Next.js + Tailwind frontend runs the game UI. The full plan is in `README.md`, and the feature specs are in `FEATURES.md`.

## Before you start a task

1. Find the feature in `FEATURES.md` and read its acceptance criteria. If the task isn't there, ask or add a spec first.
2. Keep changes scoped to that feature. Don't refactor unrelated code in the same change.
3. Build it test-first (see "Workflow: red/green TDD" below).
4. When a feature is done, tick its criteria and update its status in `FEATURES.md`.

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
# database (from the repo root)
docker compose up -d                      # Postgres in Docker: uhnime + uhnime_test

# backend (from backend/)
uv sync                                   # create/update .venv from uv.lock
uv run uvicorn app.main:app --reload
uv run pytest                             # needs TEST_DATABASE_URL (see "Test setup")
uv run pytest tests/test_normalize.py -k macron   # run one file / one test
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "msg" && uv run alembic upgrade head
uv run python -m ingest.run --source anilist --limit 100
uv run python -m jobs.seed_templates      # upsert the prompt templates (F-020)
uv run python -m jobs.generate_prompts    # generate prompts + answers from the templates (F-021)
uv run python -m jobs.generate_daily --date YYYY-MM-DD   # --date defaults to today (UTC)

# frontend (from frontend/)
npm run dev
npm test                                  # Vitest, single run
npm run test:watch                        # Vitest, watch mode
npm run lint
npm run build
```

Run the relevant tests and linters before you call a task done.

## Core domain model

Everything is a small knowledge graph. Don't add one-off tables for new question types.

The full column-level schema is in `FEATURES.md` under F-002. Summary:

- `entity`: anime, character, studio or franchise (`kind`, `canonical_name`, `popularity`, the anime-only columns `score`, `episodes`, `start_year` and `end_year` (a NULL `end_year` means still airing), `anilist_id` / `mal_id` / `wikidata_id`, `franchise_id` → the franchise entity an anime belongs to). A franchise entity carries the aliases of all its member anime. Staff and voice actors are out of scope for now (F-014).
- `entity_alias`: every name a player might type; `normalized` is the match key
- `fact`: `(subject_id, predicate, object_id | value, source)`, e.g. `(Mob Psycho 100, produced_by, Bones)`. Predicates point from the answer outward, so a prompt's answers are always fact *subjects* (`appears_in` is character → anime).
- `prompt_template` (`slug`, `answer_kind`, `query_def`) → `prompt` → `prompt_answer` (precomputed valid answers with `base_rarity`, `times_answered`)
- `daily_puzzle`: one row per `(day, position)` → prompt
- `player`, `submission`: one submission row per player per prompt, created when the prompt is served (`started_at`) and updated on each guess

A new question type is a new `prompt_template` with a `query_def` (shape defined in F-020) over `fact` and entity fields. If it needs a new predicate, add that to the ingest normalizer.

Schema conventions: `bigint` identity keys (UUID for `player`), `timestamptz` for times, and `text` + `CHECK` instead of Postgres enums.

## Rules that matter

### Answer matching
- Always match against the prompt's precomputed `prompt_answer` set, never the whole `entity` table.
- Use one normalization function for both stored aliases and user input: lowercase, NFKC, strip punctuation and whitespace, and fold macrons (ō→o, ou→o). The fold applies to every string, English words included. It lives in `backend/app/services/normalize.py`. Don't duplicate it.
- Try an exact alias match first, then `pg_trgm` similarity above `MATCH_SIMILARITY_THRESHOLD`. Every threshold change needs a test case.
- If the input matches more than one answer in the prompt equally well (e.g. the 1999 and 2011 "Hunter x Hunter"), award the more popular one.
- Franchise handling is set per template by `answer_kind`: `franchise` means one answer per franchise (any member's name matches, through the franchise's aliases), and `anime` means each season or movie is its own answer. The matcher has no franchise logic of its own; don't add any.

### Scoring
- Rarity scoring lives only in `backend/app/services/scoring.py`. Keep it a pure function of its inputs so it's easy to unit test.
- Rarity is per entry. It starts from `base_rarity` (popularity) and blends in `times_answered` as data grows. Points are fixed per rarity tier (table in F-033). Document any formula change in `FEATURES.md`.

### Game integrity
- "Day" means the UTC calendar date. The puzzle rolls over at 00:00 UTC, and every `day` column and URL segment is a UTC date.
- The server owns the timer: record when each prompt was served and reject answers after `ANSWER_TIME_LIMIT_SECONDS` (25) plus `ANSWER_GRACE_SECONDS` (default 2).
- A prompt is **finished** for a player once one of their guesses is accepted, or once its time limit plus grace has passed since it was served.
- Never send a prompt's answer list to the client before that prompt is finished.
- A player gets one accepted answer per prompt per day. Wrong guesses can be retried until the deadline, up to `MAX_GUESSES_PER_PROMPT`.

### Data ingestion
- Use official or public APIs only (AniList GraphQL, MAL API v2, Wikidata SPARQL / MediaWiki API, anime-offline-database). No HTML scraping, and nothing from Anime-Planet or IMDb pages.
- Respect rate limits: back off on 429s, cache raw responses under `backend/.cache/`, and send a descriptive User-Agent.
- Ingest must be idempotent. Re-running upserts entities by `(kind, anilist_id)` and must not create duplicates. Facts are replaced per subject and `source`, so facts removed upstream disappear here too.
- Never call external APIs from request handlers. The live game reads only from Postgres.

### Code style
- **Python:** type hints everywhere, Pydantic for I/O, `ruff` for lint and format, `pytest` for tests. Async SQLAlchemy in the API; sync SQLAlchemy in `ingest/` and `jobs/` (batch scripts, no concurrency needed). Both share the models in `app/models/`.
- **TypeScript:** strict mode, functional components, server components by default, `"use client"` only where needed (timer, input).
- **Tailwind:** utility classes inline. Extract a component rather than writing custom CSS. Keep design tokens in `tailwind.config`.
- The browser calls the API only through same-origin `/api/*` paths, which Next.js rewrites to the backend at `API_URL`. All backend routes live under `/api`.
- API responses use snake_case on the backend. The frontend API client in `frontend/lib/api.ts` maps them to camelCase.

### Secrets and config
- All config comes from env vars listed in `.env.example`. When you add a config var, add it there with a default and a comment. Never commit `.env`, API keys or cached API dumps.

## Workflow: red/green TDD

Build every feature test-first, one acceptance criterion at a time:

1. **Red:** Turn one acceptance criterion from `FEATURES.md` into a failing test. Run it and confirm it fails *for the expected reason*: an assertion failure, not an import error, syntax error or missing fixture.
2. **Green:** Write the minimum code that makes that test pass. Then run the whole relevant suite.
3. **Refactor:** Clean up while the tests stay green. Run ruff (backend) or lint (frontend).
4. Repeat for the next criterion.

Rules:
- Never weaken, skip, `xfail` or delete a test to make it pass. If a test seems wrong, stop and say so.
- Don't write implementation code that no failing test requires. Leave a `TODO(feature-id):` instead.
- Name tests after the behavior they check and include the feature ID, e.g. `test_f003_folds_macrons`.
- When you report a task done, include the final test output.
- Exempt from test-first (but still verify by running them): scaffolding and config (F-001), Alembic migrations (covered indirectly by model tests), and pure styling (F-043).

## Test setup

- **Backend:** pytest against a real Postgres database named by `TEST_DATABASE_URL` (default `uhnime_test`). Postgres runs in Docker via `docker-compose.yml`; if tests can't connect, run `docker compose up -d` rather than installing Postgres locally. SQLite won't work because matching needs `pg_trgm`. The session fixture in `backend/tests/conftest.py` runs `alembic upgrade head` once. Each test runs inside a transaction that is rolled back afterward, so tests never see each other's data. Never point tests at `DATABASE_URL`.
- API tests are async (`pytestmark = pytest.mark.anyio`) and use the `api_session` and `api_client` fixtures instead of `db_session`. Seed data with the sync factories through `await api_session.run_sync(fn)`, and set the clock by overriding the `get_now` dependency.
- Pure functions (`normalize`, `scoring`) get plain unit tests with no DB fixture.
- **Frontend:** Vitest + React Testing Library with jsdom. Test files sit next to the code as `*.test.ts(x)`. Mock `lib/api.ts`, not `fetch`.

## Testing expectations

- The matcher and scorer need unit tests with real-world anime naming cases: romaji vs English, "Shingeki no Kyojin" vs "Attack on Titan", typos, sequels.
- Every API endpoint needs at least one happy-path test and one rejection test.
- Ingest clients are tested against saved fixture responses in `backend/tests/fixtures/`, never live APIs.
- Anything time-dependent (timer, "today") takes the current time as a parameter or injectable clock, so tests never sleep or depend on the wall clock.

## When unsure

Prefer the simplest thing that satisfies the acceptance criteria in `FEATURES.md`, and leave a `TODO(feature-id):` comment for follow-ups instead of building ahead.