# FEATURES.md

The feature specs and roadmap for UH-NI-ME. Each feature has an ID, a status, a short spec and acceptance criteria. AI assistants and contributors should build against these criteria and update the status when done.

**Status legend:** `todo` · `in-progress` · `done` · `later`

---

## Milestone 0: Foundations

### F-001 · Repo scaffolding · `done`
Set up the monorepo with `frontend/` (Next.js App Router + TS + Tailwind) and `backend/` (FastAPI + SQLAlchemy + Alembic, managed with uv).
- [x] `npm run dev` serves a placeholder home page at :3000
- [x] `uv run uvicorn app.main:app` (from `backend/`) serves `GET /api/health` → `{"status": "ok"}`
- [x] Ruff and pytest added as uv dev dependencies (`uv add --dev ruff pytest`); ESLint and Prettier configured, with one passing test on each side
- [x] Vitest + React Testing Library (jsdom) set up; `npm test` and `npm run test:watch` scripts exist
- [x] `docker compose up -d` starts Postgres with the `uhnime` and `uhnime_test` databases, both with `pg_trgm`
- [x] `backend/tests/conftest.py` provides the test-DB fixture described in CLAUDE.md "Test setup" (migrate once against `TEST_DATABASE_URL`, roll back per test)
- [x] Backend reads config from env vars via a Pydantic settings class, with defaults matching `.env.example`
- [x] Next.js rewrites `/api/*` to the backend at `API_URL` (a server-side env var). The browser only ever calls same-origin `/api/...` paths, and the home page calls `/api/health` this way

### F-002 · Database schema · `done`
Create SQLAlchemy models and Alembic migrations for the schema below. Conventions: `bigint` identity keys (`GENERATED ALWAYS AS IDENTITY`) unless noted, `timestamptz` for times, `text` + `CHECK` instead of Postgres enums, and `day` is always a UTC date. Every column is `NOT NULL` unless marked `NULL`. Constraints and indexes get explicit names through a SQLAlchemy naming convention.

```
entity
  id PK, kind text CHECK (anime|character|studio|franchise)
  canonical_name text, popularity int
  start_year int NULL, end_year int NULL          -- anime only; end_year NULL = still airing
  score int NULL CHECK (0–100)                    -- anime only: average score
  CHECK ((start_year IS NULL AND end_year IS NULL AND score IS NULL) OR kind = 'anime')
  CHECK (end_year IS NULL OR (start_year IS NOT NULL AND end_year >= start_year))
  anilist_id int NULL, mal_id int NULL, wikidata_id text NULL
  franchise_id NULL → entity.id                   -- anime only: the franchise entity it belongs to
  CHECK (franchise_id IS NULL OR kind = 'anime')
  UNIQUE (kind, anilist_id); INDEX (franchise_id)

entity_alias
  id PK, entity_id → entity, alias text, normalized text CHECK (normalized <> '')
  UNIQUE (entity_id, normalized); GIN trgm (normalized)

fact
  id PK, subject_id → entity, predicate text
  object_id NULL → entity, value text NULL, source text
  CHECK (exactly one of object_id / value is set)
  UNIQUE (subject_id, predicate, object_id, source) WHERE object_id IS NOT NULL
  UNIQUE (subject_id, predicate, value, source)     WHERE value IS NOT NULL
  INDEX (predicate, object_id), (predicate, value)

prompt_template
  id PK, slug text UNIQUE, text text
  answer_kind text CHECK (anime|character|studio|franchise)
  query_def jsonb, active bool DEFAULT true

prompt
  id PK, template_id → prompt_template, params jsonb, text text, active bool DEFAULT true
  UNIQUE (template_id, params)

prompt_answer
  PK (prompt_id, entity_id), base_rarity real CHECK (0–1), times_answered int DEFAULT 0 CHECK (>= 0)

daily_puzzle
  PK (day, position), prompt_id → prompt, CHECK (position >= 1)   -- positions are 1-based
  UNIQUE (day, prompt_id); INDEX (prompt_id, day)

player
  id uuid PK DEFAULT gen_random_uuid(), created_at DEFAULT now()

submission                                        -- one row per player per prompt; created at start
  id PK, player_id → player, day date, prompt_id → prompt, started_at
  FOREIGN KEY (day, prompt_id) → daily_puzzle (day, prompt_id)   -- the prompt must be in that day's puzzle
  guess_count int DEFAULT 0, wrong_guesses text[] DEFAULT '{}'
  finished_at NULL, raw_text NULL, matched_entity_id NULL → entity   -- raw_text = the accepted input
  outcome text NULL CHECK (accepted|expired), points int NULL
  rarity_tier text NULL CHECK (larp|normie|niche|weeb|uh-ni-me)
  CHECK ((outcome IS NULL) = (finished_at IS NULL))
  CHECK ((outcome IS NOT DISTINCT FROM 'accepted') = (matched_entity_id IS NOT NULL))
  UNIQUE (player_id, day, prompt_id)
```

A submission whose deadline has passed with `outcome` still NULL counts as expired; the server writes `expired` the next time it touches the row.

Fact uniqueness includes `source`, so each source owns its own rows and two sources may assert the same fact. Anything reading facts must treat them as existence checks.

Deletes: derived data cascades and history blocks. `ON DELETE CASCADE` on `entity_alias.entity_id`, `fact.subject_id`, `fact.object_id`, `prompt_answer.prompt_id` and `prompt_answer.entity_id`. Every other foreign key is `RESTRICT`, so an entity that a player has been awarded can't be deleted.

The database does not check that `franchise_id` points at a `franchise` entity; ingest tests cover that (F-011).

- [x] `pg_trgm` extension enabled in a migration (`CREATE EXTENSION IF NOT EXISTS`; the downgrade leaves the extension in place)
- [x] All tables, constraints and indexes above exist after `alembic upgrade head`
- [x] Tests prove the constraints reject bad rows: duplicate `(kind, anilist_id)`, a fact with both or neither of `object_id` / `value`, a `start_year` on a non-anime entity, an `end_year` before `start_year` or without one, a `score` outside 0–100, an empty `normalized` alias, an unknown `answer_kind`, a `base_rarity` outside 0–1, a `position` below 1, a duplicate `(player_id, day, prompt_id)` submission, a submission for a prompt not in that day's puzzle, an `outcome` without `finished_at`, an `accepted` outcome without `matched_entity_id`, an unknown `rarity_tier`
- [x] The same fact from two different sources is allowed; the same fact twice from one source is rejected
- [x] Deleting an entity removes its aliases, facts and prompt answers; deleting an entity referenced by a submission is rejected
- [x] `alembic downgrade base` then `upgrade head` runs cleanly

### F-003 · Normalization utility · `done`
A single `normalize(text) -> str` in `backend/app/services/normalize.py`.
- [x] Lowercase, NFKC, strip punctuation and whitespace. The match key keeps only letters and digits: all whitespace is removed, not just collapsed, so `Re:Zero`, `Re Zero` and `ReZero` share a key. `×` is treated as `x` (`HUNTER×HUNTER` = `Hunter x Hunter`)
- [x] Folds macrons and long vowels (`Shōnen`, `Shounen`, `Shonen` all → `shonen`). The fold applies uniformly to every string, English words included (`your` → `yor`); this is fine because aliases and input go through the same function. The long vowels folded are `ou`/`oo` → `o` and `uu` → `u`, within a word only. Other Latin diacritics are dropped too (`Pokémon` → `pokemon`); non-Latin scripts are left as they are
- [x] Unit tests cover at least 15 real title variants, including English titles containing "ou" (e.g. `Your Name`, `Soul Eater`, `Mob Psycho 100`) so the long-vowel fold's effect on them is pinned down by tests

---

## Milestone 1: Data pipeline

### F-010 · AniList ingest client · `todo`
Fetch anime with titles, synonyms, popularity, average score, start and end dates, airing status, format, genres, relations, studios and characters through the AniList GraphQL API. Staff and voice actors are out of scope (F-014). Scope: fetching and caching raw records only. Writing to the database is F-011.
- [ ] Fetches the top N anime by popularity, excluding adult-flagged entries (`isAdult`) and the `MUSIC` format
- [ ] Fetches only characters with a `MAIN` or `SUPPORTING` role
- [ ] Paginates and backs off on HTTP 429
- [ ] Caches raw responses to `backend/.cache/anilist/`; a second run with a warm cache makes no network calls
- [ ] Sends the `INGEST_USER_AGENT` header
- [ ] Returns typed (Pydantic) source records; tested against fixtures in `backend/tests/fixtures/anilist/`

### F-011 · Normalizer → knowledge graph · `todo`
Convert source records into `entity`, `entity_alias` and `fact` rows, and wire up the `ingest.run` CLI.
- [ ] Predicates: `produced_by` (anime → studio), `appears_in` (character → anime), `format` (anime → value), `genre` (anime → value). Every fact has `source = 'anilist'`
- [ ] `entity.start_year` and `end_year` come from the anime's start and end dates (never set for characters or studios). `end_year` is NULL only while the anime is still airing; a finished anime with no end date gets `end_year = start_year`
- [ ] `entity.popularity` is AniList `popularity` for anime and `favourites` for characters and studios
- [ ] `entity.score` is AniList `averageScore` for anime (null when AniList has none; never set for other kinds)
- [ ] Every title variant (English, romaji, native, synonyms) becomes an alias
- [ ] Every anime belongs to exactly one `franchise` entity via `franchise_id`. Anime linked by sequel, prequel, parent or side-story relations share a franchise; a standalone anime gets a franchise of its own
- [ ] A franchise entity is built from its members. Its root is the member with the earliest `start_year` (ties → lowest `anilist_id`). `canonical_name` is the root's name, `anilist_id` is the root's `anilist_id` (the upsert key, unique within `kind = 'franchise'`), `popularity` is the highest member popularity, and its aliases are the union of all members' aliases
- [ ] Known limitation: if a later ingest finds an earlier root, the franchise is re-keyed and its answer history is lost. `TODO(F-011)` if this shows up in practice
- [ ] `uv run python -m ingest.run --source anilist --limit N` fetches (F-010) and upserts
- [ ] Re-running it upserts entities by `(kind, anilist_id)` and creates no duplicate entities, aliases or facts
- [ ] A fact that disappears upstream is removed on the next run (facts are replaced per subject and source)

### F-012 · MAL + ID cross-mapping · `later`
Add MyAnimeList member counts and use anime-offline-database to map IDs across sites. The "top N" templates (F-020) use AniList numbers until then and may switch to MAL here.

### F-013 · Wikidata facts · `later`
Enrich entities with facts from Wikidata (e.g. original creator, source material type).

### F-014 · Staff and voice actors · `later`
Add `staff` as an entity kind, a `voiced_by` predicate (character → staff) and the `Name a character voiced by {voice_actor}` template.

---

## Milestone 2: Prompts

### F-020 · Prompt templates · `todo`
Seed the starter templates below, each with a `query_def`. The project owner writes any further templates; don't invent new ones.
- `Name an anime produced by {studio}`
- `Name an anime airing in {year}`
- `Name an anime in the top {25|50|100|250|500} most popular anime`
- `Name an anime in the top {25|50|100|250|500} highest rated anime`
- `Name a {genre} anime airing in the {decade}s`
- `Name a character from {anime}`


A `query_def` is a JSON object with a `where` list of AND-ed conditions. The answers are the entities of the template's `answer_kind` that satisfy all of them. When `answer_kind` is `franchise`, the conditions are tested against the franchise's member anime, and a franchise is an answer if at least one member satisfies all of them. `"$name"` refers to a prompt param. Five condition types:

```json
{
  "where": [
    { "predicate": "produced_by", "object": "$studio" },
    { "predicate": "format", "value": "MOVIE" },
    { "field": "start_year", "between": ["$from", "$to"] },
    { "airing_between": ["$from", "$to"] },
    { "top": "$n", "by": "popularity" }
  ]
}
```

- `predicate` + `object`: the answer is the subject of a fact whose object is that entity
- `predicate` + `value`: the answer is the subject of a fact with that literal value
- `field` + `eq` or `between`: a condition on an `entity` column (`start_year` or `end_year`)
- `airing_between`: the anime was airing at some point in the range, i.e. `start_year <= to` and (`end_year >= from` or `end_year` is NULL). "Airing in the 2000s" is `[2000, 2009]`; "airing in 2005" is `[2005, 2005]`
- `top` + `by`: the answer is among the N highest-ranked entities of the answer kind by `popularity` or `score`. Entities with a NULL value are unranked; ties go to the higher popularity, then the lower id. The ranking is taken over all entities of that kind first, and any other conditions then filter the result

- [ ] One interpreter turns any `query_def` plus params into the list of answer entities; no per-template query code
- [ ] An unknown condition type, predicate or field raises a clear error
- [ ] Each template can list its valid answers for a given set of params
- [ ] `top` is tested for both `popularity` and `score`, including a tie at the cutoff and an entity with a NULL score
- [ ] `airing_between` is tested with a long-running anime, a still-airing anime (`end_year` NULL) and one outside the range
- [ ] Each template sets `answer_kind`, defaulting to `anime`. Every starter anime template uses `anime` for now, and the character template uses `character`. `franchise` gives one answer per franchise, and any member's name is accepted because the franchise carries all members' aliases. `anime` makes each season or movie its own answer
- [ ] Tested with a franchise whose studio changed between seasons: it is an answer for both studios under `franchise`, and only the matching seasons are answers under `anime`

### F-021 · Prompt generation + filtering · `todo`
Generate candidate prompts and precompute `prompt_answer` rows with `base_rarity`.
- [ ] Keep only prompts whose answer count is in a configured range (`PROMPT_MIN_ANSWERS`–`PROMPT_MAX_ANSWERS`, default 25–500, so a "top 25" prompt is playable)
- [ ] `base_rarity` is a log-scaled inverse of popularity, normalized to 0–1 within each prompt. Rarity is per entry: each entity in the answer set has its own value
- [ ] Regenerating an existing prompt upserts its `prompt_answer` rows and preserves `times_answered`. Answers that no longer qualify (e.g. an anime that dropped out of the top 100) are removed

### F-022 · Daily puzzle job · `todo`
`uv run python -m jobs.generate_daily --date YYYY-MM-DD` picks 7 prompts. `--date` is optional and defaults to today (UTC).
- [ ] No template appears more than twice in one day
- [ ] No prompt repeats within 60 days
- [ ] Deterministic for a given date and `PUZZLE_SEED`
- [ ] Re-running for a date that already has a puzzle is a no-op (no duplicate `daily_puzzle`)
- [ ] `--days N` (default 1) generates N consecutive days starting at `--date`. The nightly schedule runs `--days 7`, so puzzles always exist a week ahead

---

## Milestone 3: Gameplay API

### F-030 · Daily puzzle endpoint · `todo`
`GET /api/puzzle/today` returns the puzzle metadata (date, number of prompts) with no answers.
- [ ] "Today" is the current UTC date
- [ ] Response includes the player's progress: for each finished prompt its outcome, points and rarity tier, so the client can resume, show "come back tomorrow" or render the results screen
- [ ] 404 if no puzzle exists for today
- [ ] Response never contains prompt text or answers

### F-031 · Serve prompt · `todo`
`POST /api/play/{day}/prompt/{n}/start` returns the prompt text and records the server start time by creating the player's `submission` row with `started_at`.
- [ ] Prompts are served in order; prompt n requires n-1 to be finished ("finished" is defined in CLAUDE.md, Game integrity)
- [ ] `day` must be today (UTC); other days are rejected until archive mode (F-052)
- [ ] Calling start again for an already-started prompt returns the original start time and does not reset the timer
- [ ] Response includes `started_at` and `deadline` (server time) so the client can render the countdown
- [ ] Never includes answers

### F-032 · Submit answer · `todo`
`POST /api/play/{day}/prompt/{n}/answer` with `{ "text": "..." }`. The player can keep guessing until a guess is accepted or the deadline passes. Updates the `submission` row created by F-031.
- [ ] Rejects guesses for a prompt that was never started (409)
- [ ] Blank text is rejected (422) and doesn't count as a guess
- [ ] A wrong guess before the deadline returns `accepted: false, finished: false`, is appended to `wrong_guesses`, and the player may guess again
- [ ] The first valid guess is accepted: sets `outcome = accepted`, `finished_at`, `raw_text`, `matched_entity_id`, `points` and `rarity_tier`, and increments that answer's `times_answered`
- [ ] A guess after an accepted answer is rejected (409)
- [ ] A guess arriving after `ANSWER_TIME_LIMIT_SECONDS` + `ANSWER_GRACE_SECONDS` is not matched: it sets `outcome = expired` with 0 points and returns `accepted: false, finished: true`
- [ ] More than `MAX_GUESSES_PER_PROMPT` guesses on one prompt are rejected (429), so a script can't brute-force rare answers
- [ ] Matches by exact alias first, then trigram similarity above `MATCH_SIMILARITY_THRESHOLD` against the prompt's answer set
- [ ] If the input matches several answers equally well, the more popular one is awarded
- [ ] `points` and `rarity_tier` are stored at answer time and never recomputed
- [ ] Response: `{ accepted, finished, matched_name, points, rarity_tier }`. It never contains the answer list (that is F-035)

### F-033 · Scoring v1 · `todo`
Pure function in `services/scoring.py`. Points are fixed per rarity tier; the maximum for a day is 700.

| Outcome | Points |
|---|---|
| No valid answer (blank, only wrong guesses, or expired) | 0 |
| `larp` (most common answers) | 10 |
| `normie` | 30 |
| `niche` | 60 |
| `weeb` | 85 |
| `uh-ni-me` (rarest answers) | 100 |

- [ ] No valid answer → 0
- [ ] A valid answer's tier comes from its rarity (0–1) with cutoffs at 0.2, 0.4, 0.6 and 0.8. Tier names, cutoffs and points live in one constants block (the cutoffs are placeholders to tune after playtesting)
- [ ] Blends in `times_answered` once a prompt has at least `SCORING_BLEND_MIN_SUBMISSIONS` submissions
- [ ] Unit tests for each tier boundary

### F-034 · Anonymous players · `todo`
Create a player with a UUID cookie on first visit. No login for the MVP.
- [ ] A request without the cookie creates a `player` row and sets an HttpOnly, `SameSite=Lax` cookie. It is a first-party cookie because the browser reaches the API through the same-origin `/api/*` rewrite (F-001)
- [ ] A request with a valid cookie reuses the existing player
- [ ] An unknown or malformed cookie value is replaced with a new player (not a 500)

### F-035 · Prompt result and answer list · `todo`
`GET /api/play/{day}/prompt/{n}/result` returns the player's outcome for a finished prompt plus every valid answer.
- [ ] Rejected (409) until the prompt is finished for this player
- [ ] Returns the player's `outcome`, `matched_name`, `points` and `rarity_tier`
- [ ] Returns `answers`: all of the prompt's valid answers sorted alphabetically by name, each with its current `rarity_tier`
- [ ] If the deadline has passed and `outcome` is still NULL, writes `expired` before responding

---

## Milestone 4: Frontend

### F-040 · Home / start screen · `todo`
Today's date, a short "how to play", and a Start button. Shows a "come back tomorrow" state if today is already played.
- [ ] Shows today's puzzle date (UTC) from `GET /api/puzzle/today`
- [ ] Start goes to the first unfinished prompt (resumes a partly played day)
- [ ] All prompts finished → "come back tomorrow" with a link to results
- [ ] No puzzle for today → a friendly "no puzzle yet" state, not an error page

### F-041 · Prompt screen · `todo`
Prompt text, a visible 25s countdown, an autofocused input and Enter to submit.
- [ ] The countdown reflects server time (latency-tolerant)
- [ ] A wrong guess shows brief "not a valid answer" feedback, clears the input and keeps it focused so the player can retry until the timer ends
- [ ] When the prompt is finished, shows the result (accepted or time's up, matched name, points, tier) and a Next button
- [ ] The finished state includes the answer browser (from F-035): every valid answer in alphabetical order, a search box, and a filter by rarity tier. Search and filter run client-side
- [ ] Usable on mobile; the input stays visible above the on-screen keyboard

### F-042 · Results screen · `todo`
Total score, the rarity tier of each answer, and a spoiler-free share string (e.g. emoji tiers per prompt).
- [ ] Shows total score and each prompt's tier
- [ ] Each prompt row opens that prompt's answer browser (the same component as F-041)
- [ ] Share string contains the date and one emoji per prompt, and no answer text
- [ ] Copy-to-clipboard button for the share string

### F-043 · Visual identity · `todo`
Tailwind theme tokens (colors, type, spacing), with light and dark mode.
- [ ] Color, font and spacing tokens defined in `tailwind.config`, one color per rarity tier
- [ ] Dark mode follows the system setting
- [ ] Components use tokens, not raw hex values

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

- Tune after playtesting: rarity cutoffs (F-033), `MATCH_SIMILARITY_THRESHOLD` (0.4 for now) and `MAX_GUESSES_PER_PROMPT` (20 for now).
- Visual identity (F-043): palette, fonts, tier colors and share emoji. Decide before M4.
- Hosting: Vercel (frontend) + Fly/Render/Railway (API + Postgres)? Decide before deploying.