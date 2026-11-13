"""AniList GraphQL client (F-010).

Fetches the most popular anime with their relations, studios and characters, and
caches every raw response on disk. Scope is fetching only: turning these records
into entities, aliases and facts is the normalizer's job (F-011).
"""

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import httpx2
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from app.config import Settings, get_settings

API_URL = "https://graphql.anilist.co"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "anilist"

# AniList caps both list pages and character pages at these sizes.
MEDIA_PER_PAGE = 50
CHARACTERS_PER_PAGE = 25
MAX_RETRIES = 5

# Characters are sorted by role (MAIN, SUPPORTING, BACKGROUND), so paging can stop
# at the first BACKGROUND character.
CHARACTER_ROLES = frozenset({"MAIN", "SUPPORTING"})

_CHARACTERS_FIELDS = """
        pageInfo { hasNextPage }
        edges {
          role
          node { id name { full native alternative } favourites }
        }
"""

_TOP_ANIME_QUERY = """
query ($page: Int, $perPage: Int, $isAdult: Boolean, $formatNot: MediaFormat) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: $isAdult, format_not: $formatNot) {
      id
      idMal
      title { romaji english native }
      synonyms
      popularity
      averageScore
      startDate { year month day }
      endDate { year month day }
      status
      format
      genres
      relations { edges { relationType node { id type format } } }
      studios { edges { isMain node { id name favourites isAnimationStudio } } }
      characters(sort: [ROLE, RELEVANCE, ID], page: 1, perPage: __PER_PAGE__) {__CHARACTERS__      }
    }
  }
}
""".replace("__PER_PAGE__", str(CHARACTERS_PER_PAGE)).replace("__CHARACTERS__", _CHARACTERS_FIELDS)

_CHARACTERS_QUERY = """
query ($id: Int, $page: Int, $perPage: Int) {
  Media(id: $id) {
    id
    characters(sort: [ROLE, RELEVANCE, ID], page: $page, perPage: $perPage) {__CHARACTERS__    }
  }
}
""".replace("__CHARACTERS__", _CHARACTERS_FIELDS)


class AniListError(Exception):
    """AniList answered, but not with usable data."""


# --- Source records ----------------------------------------------------------


class _Record(BaseModel):
    """Field names are snake_case; AniList's camelCase keys are accepted as aliases."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AniListTitle(_Record):
    romaji: str | None = None
    english: str | None = None
    native: str | None = None


class AniListDate(_Record):
    """AniList's FuzzyDate: any part may be unknown."""

    year: int | None = None
    month: int | None = None
    day: int | None = None


class AniListRelation(_Record):
    relation_type: str  # SEQUEL, PREQUEL, PARENT, SIDE_STORY, ADAPTATION, ...
    id: int
    type: str | None = None  # ANIME or MANGA
    format: str | None = None


class AniListStudio(_Record):
    id: int
    name: str
    favourites: int | None = None
    is_main: bool = False
    is_animation_studio: bool = False


class AniListCharacterName(_Record):
    full: str | None = None
    native: str | None = None
    alternative: list[str] = []

    @field_validator("alternative", mode="before")
    @classmethod
    def _drop_empty_names(cls, value: Any) -> Any:
        return [name for name in value or [] if name]


class AniListCharacter(_Record):
    id: int
    name: AniListCharacterName
    favourites: int | None = None
    role: str  # MAIN or SUPPORTING


class AniListAnime(_Record):
    id: int
    id_mal: int | None = None
    title: AniListTitle
    synonyms: list[str] = []
    popularity: int | None = None
    average_score: int | None = None
    start_date: AniListDate = AniListDate()
    end_date: AniListDate = AniListDate()
    status: str | None = None  # FINISHED, RELEASING, NOT_YET_RELEASED, CANCELLED, HIATUS
    format: str | None = None  # TV, MOVIE, OVA, ...
    genres: list[str] = []
    relations: list[AniListRelation] = []
    studios: list[AniListStudio] = []
    characters: list[AniListCharacter] = []

    @field_validator("relations", "studios", "characters", mode="before")
    @classmethod
    def _flatten_edges(cls, value: Any) -> Any:
        """Turn a GraphQL connection ``{edges: [{..., node: {...}}]}`` into flat dicts."""
        if isinstance(value, dict) and "edges" in value:
            return [
                {**{k: v for k, v in edge.items() if k != "node"}, **edge["node"]}
                for edge in value["edges"] or []
            ]
        return value


# --- Client --------------------------------------------------------------------


class AniListClient:
    """Sync client for batch ingest. Never use it from a request handler."""

    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        http: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        per_page: int = MEDIA_PER_PAGE,
    ) -> None:
        self._user_agent = user_agent
        self._cache_dir = cache_dir
        self._http = http or httpx2.Client(timeout=30)
        self._sleep = sleep
        self._per_page = per_page

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kwargs: Any) -> Self:
        """Build a client that identifies itself with ``INGEST_USER_AGENT``."""
        settings = settings or get_settings()
        return cls(user_agent=settings.ingest_user_agent, **kwargs)

    def fetch_top_anime(self, limit: int) -> list[AniListAnime]:
        """The ``limit`` most popular anime, most popular first.

        Adult-flagged entries and the MUSIC format are excluded by AniList itself.
        """
        media: list[dict[str, Any]] = []
        page = 1
        while len(media) < limit:
            data = self._query(
                f"page-{page:04d}",
                _TOP_ANIME_QUERY,
                {"page": page, "perPage": self._per_page, "isAdult": False, "formatNot": "MUSIC"},
            )["Page"]
            media.extend(data["media"])
            if not data["pageInfo"]["hasNextPage"]:
                break
            page += 1

        return [self._parse_anime(raw) for raw in media[:limit]]

    def _parse_anime(self, raw: dict[str, Any]) -> AniListAnime:
        edges = [
            edge
            for edge in self._character_edges(raw["id"], raw["characters"])
            if edge["role"] in CHARACTER_ROLES
        ]
        return AniListAnime.model_validate({**raw, "characters": {"edges": edges}})

    def _character_edges(self, anime_id: int, first_page: dict[str, Any]) -> list[dict[str, Any]]:
        """All character edges up to the first BACKGROUND one, fetching more pages as needed."""
        edges: list[dict[str, Any]] = []
        connection = first_page
        page = 1
        while True:
            page_edges = connection["edges"] or []
            edges.extend(page_edges)
            if (
                not page_edges
                or not connection["pageInfo"]["hasNextPage"]
                or page_edges[-1]["role"] not in CHARACTER_ROLES
            ):
                return edges
            page += 1
            connection = self._query(
                f"characters-{anime_id}-{page}",
                _CHARACTERS_QUERY,
                {"id": anime_id, "page": page, "perPage": CHARACTERS_PER_PAGE},
            )["Media"]["characters"]

    def _query(self, name: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Run one GraphQL query through the cache and return its ``data``."""
        payload = {"query": query, "variables": variables}
        # The hash covers the query text, so editing a query invalidates its cache.
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
        cache_file = self._cache_dir / f"{name}-{digest}.json"

        # TODO(F-011): the cache never expires; the nightly run needs a way to refresh it.
        if cache_file.exists():
            return json.loads(cache_file.read_text())["data"]

        body = self._post(payload)
        if body.get("errors") or not body.get("data"):
            raise AniListError(f"AniList query {name} failed: {body.get('errors')}")

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(body, ensure_ascii=False))
        return body["data"]

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to AniList, waiting and retrying while it answers 429."""
        for attempt in range(MAX_RETRIES + 1):
            response = self._http.post(
                API_URL,
                json=payload,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            )
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            if attempt < MAX_RETRIES:
                self._sleep(_retry_delay(response, attempt))

        raise AniListError(f"AniList still answered 429 after {MAX_RETRIES} retries")


def _retry_delay(response: httpx2.Response, attempt: int) -> float:
    """Seconds to wait: the server's ``Retry-After`` if it sent one, else 1, 2, 4, ..."""
    try:
        return max(float(response.headers["Retry-After"]), 0)
    except (KeyError, ValueError):
        return float(2**attempt)
