# UH-NI-ME

A daily anime trivia game where **rare answers score more**. Inspired by Krillion.

Every day, everyone gets the same 7 open-ended prompts, like *"Name an anime produced by MAPPA"* or *"Name a character from Fullmetal Alchemist: Brotherhood."* You have 25 seconds per prompt and can keep guessing until one answer lands. Any valid answer is accepted, and the more obscure it is, the more points it earns.

> Status: pre-MVP. See [FEATURES.md](FEATURES.md) for the roadmap and feature specs.

---

## How it works

```
Nightly batch                                Live game
─────────────                                ─────────
AniList / MAL / Wikidata                     Web client (Next.js)
        │                                           │
        ▼                                           ▼
Ingest worker ──► Postgres ◄── Prompt job    Game API (FastAPI)
 (normalize,      (entities,   (picks the           │
  build aliases)   facts,       daily 7)            ▼
                   answers)  ◄───────────── Answer matcher ──► Scorer
```

1. **Ingest (nightly):** Pull anime, characters and studios from public APIs into a small knowledge graph (`entity`, `entity_alias`, `fact`).
2. **Prompt generation:** Fill prompt templates (e.g. `Name an anime by {studio}`), compute each prompt's full set of valid answers, and keep only prompts with a playable answer count.
3. **Daily puzzle:** Choose 7 prompts, with no template used more than twice.
4. **Play:** The client submits free-text answers. The matcher resolves them against aliases with fuzzy matching, and the scorer awards points based on rarity.
5. **Rarity:** Starts as inverse popularity (AniList/MAL member counts), then blends in how often real players give each answer.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React, Next.js (App Router), TypeScript, Tailwind CSS |
| Backend API | Python, FastAPI, Pydantic, SQLAlchemy |
| Database | PostgreSQL with the `pg_trgm` extension (fuzzy matching) |
| Batch jobs | Python scripts run on a schedule (ingest + daily prompt job) |

## Repository layout

```
uh-ni-me/
├── frontend/              # Next.js app
│   ├── app/               # App Router routes
│   ├── components/
│   └── lib/               # API client, utils
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routers
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # matcher, scorer, puzzle logic
│   │   └── main.py
│   ├── ingest/            # source clients + nightly ingest
│   ├── jobs/              # daily prompt generation
│   ├── migrations/        # Alembic
│   ├── tests/
│   ├── pyproject.toml     # Python deps (uv)
│   ├── uv.lock
│   └── .python-version
├── docker-compose.yml     # local Postgres
├── docker/postgres/       # database init script
├── README.md
├── CLAUDE.md              # instructions for AI coding assistants
├── FEATURES.md            # feature specs + roadmap
└── .env.example
```

## Getting started

### Prerequisites

- Node.js (LTS) and npm
- [uv](https://docs.astral.sh/uv/) (installs and manages Python 3.13 for the backend)
- Docker (runs PostgreSQL 17 with the `pg_trgm` extension)

### 1. Environment

```bash
cp .env.example .env
# check DATABASE_URL / TEST_DATABASE_URL and set INGEST_USER_AGENT
echo "API_URL=http://localhost:8000" > frontend/.env.local   # Next.js reads env from frontend/ and proxies /api/* to this
```

`MAL_CLIENT_ID` is only needed once MAL ingest (F-012) lands.

### 2. Database

```bash
docker compose up -d        # Postgres on localhost:5432
```

The first start creates two databases, `uhnime` (development) and `uhnime_test` (used by pytest; tests never touch the dev DB), and enables `pg_trgm` in both. Useful commands:

```bash
docker compose exec db psql -U uhnime uhnime   # open a SQL shell
docker compose down                            # stop; data is kept
docker compose down -v                         # stop and wipe all data
```

### 3. Backend

```bash
cd backend
uv sync                                  # creates .venv and installs locked deps
uv run alembic upgrade head
uv run uvicorn app.main:app --reload     # http://localhost:8000  (docs at /docs)
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

### 5. Seed data

```bash
cd backend
uv run python -m ingest.run --source anilist --limit 500   # small dev seed
uv run python -m jobs.seed_templates                        # upsert the prompt templates
uv run python -m jobs.generate_prompts                      # prompts + answers from the templates
uv run python -m jobs.generate_daily --days 7               # --date defaults to today (UTC)
```

## Data sources and etiquette

UH-NI-ME uses **official or public APIs and datasets**, not HTML scraping:

- **AniList** (GraphQL API): primary source for titles, synonyms, characters, studios and popularity
- **MyAnimeList** (official API v2, needs a client ID): member counts and cross-checks
- **Wikidata / Wikipedia** (SPARQL / MediaWiki API): structured facts such as studios and air dates
- **anime-offline-database**: cross-site ID mapping

Ingest jobs cache responses, respect each API's rate limits and identify themselves with a descriptive User-Agent. Sources without a public API, or whose terms forbid scraping (e.g. Anime-Planet, IMDb pages), are out of scope.

UH-NI-ME is a fan project and is not affiliated with any of these sites or with Krillion.

## Contributing

See [CLAUDE.md](CLAUDE.md) for conventions (they apply to humans too) and [FEATURES.md](FEATURES.md) for what to build next.

## License

TBD