# FEATURES.md

The feature specs and roadmap for UH-NI-ME. Each feature has an ID, a status, a short spec and acceptance criteria. AI assistants and contributors should build against these criteria and update the status when done.

**Status legend:** `todo` · `in-progress` · `done` · `later`

---

## Milestone 0: Foundations

### F-001 · Repo scaffolding · `todo`
Set up the monorepo with `frontend/` (Next.js App Router + TS + Tailwind) and `backend/` (FastAPI + SQLAlchemy + Alembic, managed with uv).
- [ ] `npm run dev` serves a placeholder home page at :3000
- [ ] `uv run uvicorn app.main:app` (from `backend/`) serves `GET /health` → `{"status": "ok"}`
- [ ] Ruff and pytest added as uv dev dependencies (`uv add --dev ruff pytest`); ESLint and Prettier configured, with one passing test on each side
- [ ] Frontend reads `NEXT_PUBLIC_API_URL` and calls `/health`

### F-002 · Database schema · `todo`
Create Alembic migrations for `entity`, `entity_alias`, `fact`, `prompt_template`, `prompt`, `prompt_answer`, `daily_puzzle`, `player` and `submission` (see README / CLAUDE.md).
- [ ] `pg_trgm` extension enabled in a migration
- [ ] GIN trigram index on `entity_alias.normalized`
- [ ] Unique constraint that keeps ingest idempotent (source id per entity)
- [ ] Unique `(player_id, prompt_id, day)` on submissions

### F-003 · Normalization utility · `todo`
A single `normalize(text) -> str` in `backend/app/services/normalize.py`.
- [ ] Lowercase, NFKC, strip punctuation and extra whitespace
- [ ] Folds macrons and long vowels (`Shōnen`, `Shounen`, `Shonen` all → `shonen`)
- [ ] Unit tests cover at least 15 real title variants

---

## Milestone 1: Data pipeline

### F-010 · AniList ingest client · `todo`
Fetch anime with titles, synonyms, popularity, studios, characters and voice actors through the AniList GraphQL API.
- [ ] Paginates and backs off on HTTP 429
- [ ] Caches raw responses to `backend/.cache/anilist/`
- [ ] `uv run python -m ingest.run --source anilist --limit N` works
- [ ] Re-running it creates no duplicates

### F-011 · Normalizer → knowledge graph · `todo`
Convert source records into `entity`, `entity_alias` and `fact` rows.
- [ ] Predicates: `produced_by` (studio), `has_character`, `voiced_by`, `aired_year`, `format`, `genre`
- [ ] Every title variant (English, romaji, native, synonyms) becomes an alias
- [ ] `franchise_id` groups sequels and seasons where the source provides relations

### F-012 · MAL + ID cross-mapping · `later`
Add MyAnimeList member counts and use anime-offline-database to map IDs across sites.

### F-013 · Wikidata facts · `later`
Enrich entities with facts from Wikidata (e.g. original creator, source material type).

---

## Milestone 2: Prompts

### F-020 · Prompt templates · `todo`
Seed 5–10 templates, each with a `query_def` over `fact`. Starter set:
- `Name an anime produced by {studio}`
- `Name a character voiced by {voice_actor}`
- `Name a {genre} anime from the {decade}s`
- `Name an anime that aired in {year}`
- `Name a character from {anime}`
- `Name an anime movie from {studio}`
- [ ] Each template can list its valid answers for a given set of params

### F-021 · Prompt generation + filtering · `todo`
Generate candidate prompts and precompute `prompt_answer` rows with `base_rarity`.
- [ ] Keep only prompts whose answer count is in a configured range (default 30–500)
- [ ] `base_rarity` comes from popularity (e.g. a log-scaled inverse), normalized to 0–1 within each prompt

### F-022 · Daily puzzle job · `todo`
`uv run python -m jobs.generate_daily --date YYYY-MM-DD` picks 7 prompts.
- [ ] No template appears more than twice in one day
- [ ] No prompt repeats within 60 days
- [ ] Deterministic for a given date and seed

---

## Milestone 3: Gameplay API

### F-030 · Daily puzzle endpoint · `todo`
`GET /api/puzzle/today` returns the puzzle metadata (date, number of prompts) with no answers.

### F-031 · Serve prompt · `todo`
`POST /api/play/{day}/prompt/{n}/start` returns the prompt text and records the server start time.
- [ ] Prompts are served in order; prompt n requires n-1 to be finished
- [ ] Never includes answers

### F-032 · Submit answer · `todo`
`POST /api/play/{day}/prompt/{n}/answer` with `{ "text": "..." }`.
- [ ] Rejects answers after 25s plus grace, and second submissions
- [ ] Matches by exact alias first, then trigram similarity against the prompt's answer set
- [ ] Response: `{ accepted, matched_name, points, rarity_tier, top_answers }`. `top_answers` is revealed only after submitting.

### F-033 · Scoring v1 · `todo`
Pure function in `services/scoring.py`.
- [ ] Wrong or expired answer → 0
- [ ] Valid answer → points scaled by rarity, with 6 rarity tiers (common → legendary)
- [ ] Blends in `times_answered` once a prompt has at least N submissions (configurable)
- [ ] Unit tests for each tier boundary

### F-034 · Anonymous players · `todo`
Create a player with a UUID cookie on first visit. No login for the MVP.

---

## Milestone 4: Frontend

### F-040 · Home / start screen · `todo`
Today's date, a short "how to play", and a Start button. Shows a "come back tomorrow" state if today is already played.

### F-041 · Prompt screen · `todo`
Prompt text, a visible 25s countdown, an autofocused input and Enter to submit.
- [ ] The countdown reflects server time (latency-tolerant)
- [ ] Shows the result (accepted, matched name, points, tier) before moving on
- [ ] Usable on mobile; the input stays visible above the on-screen keyboard

### F-042 · Results screen · `todo`
Total score, the rarity tier of each answer, and a spoiler-free share string (e.g. emoji tiers per prompt).

### F-043 · Visual identity · `todo`
Tailwind theme tokens (colors, type, spacing), with light and dark mode.

---

## Later

- **F-050** Global daily leaderboard
- **F-051** Accounts (OAuth) and streaks
- **F-052** Archive mode for playing past days
- **F-053** Character image hints after answering (respecting source licensing)
- **F-054** Admin page to review, retire or hand-edit prompts and aliases
- **F-055** Player-reported "this should be accepted" alias suggestions

---

## Open questions

- Franchise rule: does "Fate/Zero" count as a separate answer from "Fate/stay night"? Decide per template.
- Exact scoring curve and tier cutoffs: tune after playtesting.
- Hosting: Vercel (frontend) + Fly/Render/Railway (API + Postgres)? Decide before M3.