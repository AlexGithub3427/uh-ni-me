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
  episodes int NULL                               -- anime only: episode count (F-015)
  CHECK ((start_year IS NULL AND end_year IS NULL AND score IS NULL AND episodes IS NULL) OR kind = 'anime')
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

### F-010 · AniList ingest client · `done`
Fetch anime with titles, synonyms, popularity, average score, start and end dates, airing status, format, genres, relations, studios and characters through the AniList GraphQL API. Staff and voice actors are out of scope (F-014). Scope: fetching and caching raw records only. Writing to the database is F-011.
- [x] Fetches the top N anime by popularity, excluding adult-flagged entries (`isAdult`) and the `MUSIC` format
- [x] Fetches only characters with a `MAIN` or `SUPPORTING` role
- [x] Paginates and backs off on HTTP 429
- [x] Caches raw responses to `backend/.cache/anilist/`; a second run with a warm cache makes no network calls
- [x] Sends the `INGEST_USER_AGENT` header
- [x] Returns typed (Pydantic) source records; tested against fixtures in `backend/tests/fixtures/anilist/`

### F-011 · Normalizer → knowledge graph · `done`
Convert source records into `entity`, `entity_alias` and `fact` rows, and wire up the `ingest.run` CLI.
- [x] Predicates: `produced_by` (anime → studio), `appears_in` (character → anime), `format` (anime → value), `genre` (anime → value). Every fact has `source = 'anilist'`. `produced_by` covers AniList's animation studios only (`isAnimationStudio`), main or not; licensors and publishers get no studio entity
- [x] `entity.start_year` and `end_year` come from the anime's start and end dates (never set for characters or studios). `end_year` is NULL only while the anime is still airing; a finished anime with no end date gets `end_year = start_year`
- [x] `entity.popularity` is AniList `popularity` for anime and `favourites` for characters and studios
- [x] `entity.score` is AniList `averageScore` for anime (null when AniList has none; never set for other kinds)
- [x] Every title variant (English, romaji, native, synonyms) becomes an alias; characters get their full, native and alternative names. `canonical_name` is the first available of English, romaji, native (characters: full, native). Names with an empty match key are skipped. Ingest only adds aliases and never removes them, because `entity_alias` has no `source`
- [x] Every anime belongs to exactly one `franchise` entity via `franchise_id`. Anime linked by sequel, prequel, parent or side-story relations share a franchise; a standalone anime gets a franchise of its own. Two fetched anime that both link to the same unfetched anime also share a franchise
- [x] A franchise entity is built from its members. Its root is the member with the earliest `start_year` (ties → lowest `anilist_id`). `canonical_name` is the root's name, `anilist_id` is the root's `anilist_id` (the upsert key, unique within `kind = 'franchise'`), `popularity` is the highest member popularity, and its aliases are the union of all members' aliases
- [x] Known limitation: if a later ingest finds an earlier root, the franchise is re-keyed and its answer history is lost. `TODO(F-011)` if this shows up in practice
- [x] `uv run python -m ingest.run --source anilist --limit N` fetches (F-010) and upserts
- [x] Re-running it upserts entities by `(kind, anilist_id)` and creates no duplicate entities, aliases or facts
- [x] A fact that disappears upstream is removed on the next run (facts are replaced per subject and source). An anime's record owns its own facts and the `appears_in` facts pointing at it, so a character keeps its facts about anime that were not refetched

### F-012 · MAL + ID cross-mapping · `later`
Add MyAnimeList member counts and use anime-offline-database to map IDs across sites. The "top N" templates (F-020) use AniList numbers until then and may switch to MAL here.

### F-013 · Wikidata facts · `later`
Enrich entities with facts from Wikidata (e.g. original creator, source material type).

### F-014 · Staff and voice actors · `later`
Add `staff` as an entity kind, a `voiced_by` predicate (character → staff) and the `Name a character voiced by {voice_actor}` template.

### F-015 · AniList tags, source material and episode counts · `done`
Extend the AniList client (F-010) and the normalizer (F-011) with three more fields. Ingest only: the templates that use them are seeded in F-020.
- [x] The client also fetches `tags` (name, rank, spoiler and adult flags), `source` and `episodes`; fixtures updated
- [x] `tag` predicate (anime → value): one fact per tag whose rank is at least `TAG_MIN_RANK` (default 60, in `.env.example`). Spoiler tags (general or for that anime) and adult tags are skipped
- [x] `source_material` predicate (anime → value) holds AniList's `source` (`ORIGINAL`, `MANGA`, `LIGHT_NOVEL`, `VIDEO_GAME`, `VISUAL_NOVEL`, ...). No fact when AniList has none. It is not named `source` because `fact.source` already means the data source
- [x] `entity.episodes` (int NULL, anime only) holds AniList `episodes`, added by a migration and to the F-002 schema listing. The anime-only `CHECK` on `entity` is extended to cover it. It is a column and not a fact because prompts compare it numerically
- [x] Re-running stays idempotent, and a tag or source removed upstream disappears on the next run

---

## Milestone 2: Prompts

### F-020 · Prompt templates · `todo`
Seed the templates below, each with a `query_def`. The project owner writes any further templates; don't invent new ones.

Anime answers (`answer_kind = anime`):
- `Name an anime by {studio}`
- `Name an anime that aired in {year}`
- `Name an anime that premiered in {year}` (stricter than "aired in": a long-runner counts only in its first year)
- `Name an anime in the top {25|50|100|250|500} most popular anime`
- `Name an anime in the top {25|50|100|250|500} highest rated anime`
- `Name a {genre} anime`
- `Name a {genre} and {genre} anime`
- `Name a {genre} anime airing in the {decade}s`
- `Name a {genre} anime by {studio}`
- `Name a {studio} anime from the {decade}s`
- `Name an anime in the top {25|50|100} most popular {genre} anime` (ranked within the genre, using `within`)
- `Name an anime from the top {25|50|100|250} highest rated {decade}'s anime` (ranked within the decade, using `within` with `airing_between`)
- `Name an anime movie from the {decade}s`
- `Name a {genre} anime movie`
- `Name an anime movie by {studio}`
- `Name an anime rated {80|85}+`
- `Name an anime rated below {60|65}`
- `Name an anime currently airing`
- `Name an anime that ran for {3|5|10}+ years`

Franchise answers (`answer_kind = franchise`):
- `Name a franchise with an anime movie`
- `Name a franchise with an anime by {studio}`
- `Name a franchise with an anime that aired in the {decade}s`
- `Name a franchise with {3|5|10}+ anime`

Character answers (`answer_kind = character`):
- `Name a character from {anime}`
- `Name a character from the {franchise} franchise`
- `Name a character from a {studio} anime`
- `Name a character from an anime that aired in {year}`
- `Name one of the top {25|50|100|250} most favourited characters`

Anime answers that use the F-015 data (`answer_kind = anime`):
- `Name a {tag} anime` (e.g. isekai, time travel, mecha, sports)
- `Name an original anime`
- `Name an anime adapted from a {manga|light novel|video game|visual novel}`
- `Name an anime with {100|200}+ episodes`
- `Name a TV anime with 13 or fewer episodes` (`format = TV` only, so movies, OVAs, ONAs, specials and TV shorts are not answers)

A `query_def` is a JSON object with a `where` list of AND-ed conditions. The answers are the entities of the template's `answer_kind` that satisfy all of them. When `answer_kind` is `franchise`, the conditions are tested against the franchise's member anime, and a franchise is an answer if at least one member satisfies all of them (`min_members` is the exception: it tests the franchise itself). `"$name"` refers to a prompt param. Eight condition types:

```json
{
  "where": [
    { "predicate": "produced_by", "object": "$studio" },
    { "predicate": "format", "value": "MOVIE" },
    { "predicate": "appears_in", "object_where": [{ "predicate": "produced_by", "object": "$studio" }] },
    { "field": "start_year", "between": ["$from", "$to"] },
    { "airing_between": ["$from", "$to"] },
    { "ran_for": "$years", "as_of": "$year" },
    { "top": "$n", "by": "popularity" },
    { "top": "$n", "by": "popularity", "within": [{ "predicate": "genre", "value": "$genre" }] },
    { "min_members": "$n" }
  ]
}
```

- `predicate` + `object`: the answer is the subject of a fact whose object is that entity
- `predicate` + `value`: the answer is the subject of a fact with that literal value
- `predicate` + `object_where`: the answer is the subject of a fact whose object satisfies every condition in the nested list. The nested list takes the same condition types, tested against the object entity, except `top`, `min_members` and another `object_where` (one level of nesting only). "A character from a {studio} anime" is the example above
- `field` + one of `eq`, `between`, `gte`, `lte`, `is_null`: a condition on an `entity` column (`start_year`, `end_year`, `score`, `episodes` or `franchise_id`; `franchise_id` takes `eq` only). `between` is inclusive. `is_null` takes `true` or `false`. A NULL column fails every operator except `is_null: true`. Scores are whole numbers, so "rated below 60" is `lte: 59`
- `airing_between`: the anime was airing at some point in the range, i.e. `start_year <= to` and (`end_year >= from` or `end_year` is NULL). "Airing in the 2000s" is `[2000, 2009]`; "airing in 2005" is `[2005, 2005]`
- `ran_for` + `as_of`: the anime spans at least that many years, i.e. `coalesce(end_year, as_of) - start_year >= years`. `as_of` is the year the prompt was generated and stands in for the end of an anime that is still airing. It compares calendar years, so it is approximate. An anime with no `start_year` never qualifies
- `top` + `by`: the answer is among the N highest-ranked entities of the answer kind by `popularity` or `score`. Entities with a NULL value are unranked; ties go to the higher popularity, then the lower id. The ranking is taken over all entities of that kind first, and any other conditions then filter the result
- `top` + `by` + `within`: the same, but the ranking is taken only over the entities of the answer kind that satisfy every condition in the `within` list, so "the top 25 most popular {genre} anime" is the example above. If fewer than N entities satisfy `within`, all of the ranked ones are answers. The `within` list takes the same condition types except `top` and `min_members`. Conditions outside `within` still filter the result afterwards
- `min_members`: the franchise has at least N member anime, of any format. Valid only when `answer_kind` is `franchise`

"Currently airing" is `end_year` `is_null: true` plus `start_year` `lte: "$year"`, where `$year` is the year the prompt was generated. The second condition excludes anime that have not started yet, which also have a NULL `end_year`.

- [ ] One interpreter turns any `query_def` plus params into the list of answer entities; no per-template query code
- [ ] An unknown condition type, predicate, field or operator raises a clear error. So do `top`, `min_members` or `object_where` inside an `object_where`, `top` or `min_members` inside a `within`, and `min_members` with an `answer_kind` other than `franchise`
- [ ] Each template can list its valid answers for a given set of params
- [ ] `top` is tested for both `popularity` and `score`, including a tie at the cutoff and an entity with a NULL score. It is also tested with `answer_kind = character`, where it ranks characters only
- [ ] `top` with `within` is tested with a popular anime outside the genre (it takes no rank, so the genre's Nth anime is still an answer), a tie at the cutoff inside the genre, a genre with fewer than N anime (all are answers), and a second condition outside `within` that filters the ranked result
- [ ] `airing_between` is tested with a long-running anime, a still-airing anime (`end_year` NULL) and one outside the range
- [ ] `field` is tested for each operator, including a NULL `score` that fails `gte` and `lte`
- [ ] "Currently airing" is tested with a still-airing anime, a finished one and one that has not started yet; only the first is an answer
- [ ] `ran_for` is tested with a finished long-runner, a still-airing anime measured against `as_of`, and one that is too short
- [ ] `object_where` is tested for the three character templates that use it (franchise, studio and year): a character is an answer if at least one anime they appear in satisfies the nested conditions, and appears once even when several do
- [ ] `min_members` is tested at the cutoff: a franchise with exactly N members is an answer and one with N − 1 is not
- [ ] Each template sets `answer_kind` as grouped in the list above, defaulting to `anime`. `franchise` gives one answer per franchise, and any member's name is accepted because the franchise carries all members' aliases. `anime` makes each season or movie its own answer
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
- Stale answer sets: "currently airing" and `ran_for` prompts (F-020) depend on the year they were generated, and an anime can end after its prompt was generated. Decide how close to its puzzle day such a prompt must be regenerated (F-021, F-022).
- Catalogue size: how many anime should production hold (`--limit`)? Only the 500-anime dev seed is defined. Decide before the first production ingest, once prompts exist and their answer counts can be checked.
- Ingest cache expiry: the F-010 cache never expires, so a scheduled ingest with a warm cache fetches nothing new. Add a max age or a `--refresh` flag (`TODO(F-011)` in `ingest/anilist.py`). Until then, delete `backend/.cache/anilist/` to refetch. Decide before scheduling the ingest.
- Ingest refresh schedule: how often to refetch, and whether to refresh the most popular anime more often than the long tail. AniList allows 30 requests per minute, so a large catalogue takes hours. Depends on catalogue size; measure a full run first. Decide before scheduling the ingest.
- Anime that fall out of the top N are no longer refetched, and their rows stay as last ingested. Revisit after launch if stale entries show up.
- Where the scheduled jobs run (ingest and the daily puzzle job), and which feature covers setting that up. Decide with hosting.