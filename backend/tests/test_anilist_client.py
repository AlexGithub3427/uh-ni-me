"""F-010: AniList ingest client, tested against saved responses in fixtures/anilist/."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.config import Settings
from ingest.anilist import (
    DEFAULT_CACHE_DIR,
    AniListAnime,
    AniListClient,
    AniListError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "anilist"
BACKEND_DIR = Path(__file__).resolve().parents[1]

ATTACK_ON_TITAN = 16498
DEMON_SLAYER = 101922

Handler = Callable[[httpx2.Request], httpx2.Response]


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _variables(request: httpx2.Request) -> dict[str, Any]:
    return json.loads(request.content)["variables"]


def _fixture_response(request: httpx2.Request) -> httpx2.Response:
    """Answer like AniList would, from the saved responses.

    The fixtures were recorded with one anime per page, so tests use ``per_page=1``.
    """
    variables = _variables(request)
    if "id" in variables:
        name = f"characters-{variables['id']}-{variables['page']}.json"
    else:
        name = f"page-{variables['page']}.json"
    return httpx2.Response(200, json=_fixture(name))


class FakeAniList:
    """A mock transport that records every request it receives."""

    def __init__(self, handler: Handler = _fixture_response) -> None:
        self.requests: list[httpx2.Request] = []
        self._handler = handler

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def http(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self))


def _client(
    api: FakeAniList,
    cache_dir: Path,
    *,
    per_page: int = 1,
    sleep: Callable[[float], None] | None = None,
) -> AniListClient:
    return AniListClient(
        user_agent="test-agent/1.0",
        cache_dir=cache_dir,
        http=api.http,
        per_page=per_page,
        sleep=sleep or (lambda seconds: None),
    )


# --- Top N by popularity ---------------------------------------------------


def test_f010_fetches_top_n_anime_in_popularity_order(tmp_path: Path) -> None:
    api = FakeAniList()

    anime = _client(api, tmp_path).fetch_top_anime(2)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN, DEMON_SLAYER]
    assert anime[0].popularity > anime[1].popularity
    query = json.loads(api.requests[0].content)["query"]
    assert "type: ANIME" in query
    assert "sort: POPULARITY_DESC" in query


def test_f010_excludes_adult_entries_and_music_format(tmp_path: Path) -> None:
    api = FakeAniList()

    _client(api, tmp_path).fetch_top_anime(2)

    page_requests = [r for r in api.requests if "id" not in _variables(r)]
    assert page_requests
    for request in page_requests:
        assert _variables(request)["isAdult"] is False
        assert _variables(request)["formatNot"] == "MUSIC"
        query = json.loads(request.content)["query"]
        assert "isAdult: $isAdult" in query
        assert "format_not: $formatNot" in query


def test_f010_stops_requesting_pages_once_it_has_n(tmp_path: Path) -> None:
    api = FakeAniList()

    anime = _client(api, tmp_path).fetch_top_anime(1)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN]
    assert [_variables(r)["page"] for r in api.requests if "id" not in _variables(r)] == [1]


def test_f010_truncates_a_page_that_overshoots_n(tmp_path: Path) -> None:
    both = _fixture("page-1.json")
    both["data"]["Page"]["media"] += _fixture("page-2.json")["data"]["Page"]["media"]

    def handler(request: httpx2.Request) -> httpx2.Response:
        if "id" in _variables(request):
            return _fixture_response(request)
        return httpx2.Response(200, json=both)

    api = FakeAniList(handler)

    anime = _client(api, tmp_path, per_page=2).fetch_top_anime(1)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN]
    # No character follow-ups for the anime that was cut off.
    assert all(_variables(r).get("id") != DEMON_SLAYER for r in api.requests)


def test_f010_stops_when_anilist_has_no_more_pages(tmp_path: Path) -> None:
    last_page = _fixture("page-2.json")
    last_page["data"]["Page"]["pageInfo"]["hasNextPage"] = False

    def handler(request: httpx2.Request) -> httpx2.Response:
        variables = _variables(request)
        if "id" not in variables and variables["page"] == 2:
            return httpx2.Response(200, json=last_page)
        return _fixture_response(request)

    api = FakeAniList(handler)

    anime = _client(api, tmp_path).fetch_top_anime(10)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN, DEMON_SLAYER]


# --- Characters ------------------------------------------------------------


def test_f010_returns_only_main_and_supporting_characters(tmp_path: Path) -> None:
    api = FakeAniList()

    titan, slayer = _client(api, tmp_path).fetch_top_anime(2)

    assert {c.role for c in titan.characters} == {"MAIN", "SUPPORTING"}
    assert {c.role for c in slayer.characters} == {"MAIN", "SUPPORTING"}
    # Recorded data: 3 MAIN + 77 SUPPORTING (the last page also has 7 BACKGROUND).
    assert len(titan.characters) == 80
    assert [c.name.full for c in titan.characters if c.role == "MAIN"] == [
        "Eren Yeager",
        "Mikasa Ackerman",
        "Armin Arlert",
    ]
    assert len(slayer.characters) == 72
    assert len({c.id for c in titan.characters}) == 80


def test_f010_pages_through_characters_until_the_first_background_role(tmp_path: Path) -> None:
    api = FakeAniList()

    _client(api, tmp_path).fetch_top_anime(2)

    character_pages = [(v["id"], v["page"]) for v in map(_variables, api.requests) if "id" in v]
    # Demon Slayer's page 3 already contains BACKGROUND characters, so page 4
    # (which exists upstream) is never requested.
    assert character_pages == [
        (ATTACK_ON_TITAN, 2),
        (ATTACK_ON_TITAN, 3),
        (ATTACK_ON_TITAN, 4),
        (DEMON_SLAYER, 2),
        (DEMON_SLAYER, 3),
    ]
    for request in api.requests:
        assert "sort: [ROLE, RELEVANCE, ID]" in json.loads(request.content)["query"]


# --- 429 backoff -----------------------------------------------------------


def _rate_limited(times: int, headers: dict[str, str] | None = None) -> Handler:
    """Answer 429 for the first ``times`` requests, then serve fixtures."""
    remaining = [times]

    def handler(request: httpx2.Request) -> httpx2.Response:
        if remaining[0] > 0:
            remaining[0] -= 1
            return httpx2.Response(429, headers=headers or {}, json={"errors": []})
        return _fixture_response(request)

    return handler


def test_f010_waits_for_retry_after_on_429_then_retries(tmp_path: Path) -> None:
    api = FakeAniList(_rate_limited(1, {"Retry-After": "7"}))
    sleeps: list[float] = []

    anime = _client(api, tmp_path, sleep=sleeps.append).fetch_top_anime(1)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN]
    assert sleeps == [7]


def test_f010_backs_off_exponentially_on_429_without_retry_after(tmp_path: Path) -> None:
    api = FakeAniList(_rate_limited(3))
    sleeps: list[float] = []

    anime = _client(api, tmp_path, sleep=sleeps.append).fetch_top_anime(1)

    assert [a.id for a in anime] == [ATTACK_ON_TITAN]
    assert sleeps == [1, 2, 4]


def test_f010_gives_up_after_too_many_429s(tmp_path: Path) -> None:
    api = FakeAniList(_rate_limited(1000))
    sleeps: list[float] = []

    with pytest.raises(AniListError, match="429"):
        _client(api, tmp_path, sleep=sleeps.append).fetch_top_anime(1)

    assert len(sleeps) == 5
    assert not list(tmp_path.iterdir())


# --- Cache -----------------------------------------------------------------


def test_f010_default_cache_dir_is_backend_cache_anilist() -> None:
    assert DEFAULT_CACHE_DIR == BACKEND_DIR / ".cache" / "anilist"


def test_f010_warm_cache_makes_no_network_calls(tmp_path: Path) -> None:
    cold = FakeAniList()
    first = _client(cold, tmp_path).fetch_top_anime(2)
    assert len(cold.requests) == 7

    warm = FakeAniList()
    second = _client(warm, tmp_path).fetch_top_anime(2)

    assert warm.requests == []
    assert second == first


def test_f010_caches_raw_responses_as_json_files(tmp_path: Path) -> None:
    cache_dir = tmp_path / "anilist"

    _client(FakeAniList(), cache_dir).fetch_top_anime(1)

    cached = [json.loads(path.read_text()) for path in sorted(cache_dir.glob("*.json"))]
    assert len(cached) == 4  # one list page + three character pages
    assert _fixture("page-1.json") in cached


def test_f010_does_not_cache_graphql_errors(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"errors": [{"message": "boom"}], "data": None})

    with pytest.raises(AniListError, match="boom"):
        _client(FakeAniList(handler), tmp_path).fetch_top_anime(1)

    assert not list(tmp_path.iterdir())


def test_f010_raises_on_other_http_errors_without_retrying(tmp_path: Path) -> None:
    api = FakeAniList(lambda request: httpx2.Response(500, text="oops"))
    sleeps: list[float] = []

    with pytest.raises(httpx2.HTTPStatusError):
        _client(api, tmp_path, sleep=sleeps.append).fetch_top_anime(1)

    assert len(api.requests) == 1
    assert sleeps == []


# --- User-Agent ------------------------------------------------------------


def test_f010_sends_the_ingest_user_agent_on_every_request(tmp_path: Path) -> None:
    api = FakeAniList()
    settings = Settings(
        _env_file=None, ingest_user_agent="uh-ni-me-test/9.9 (+https://example.org)"
    )

    client = AniListClient.from_settings(settings, cache_dir=tmp_path, http=api.http, per_page=1)
    client.fetch_top_anime(1)

    assert len(api.requests) == 4
    for request in api.requests:
        assert request.headers["User-Agent"] == "uh-ni-me-test/9.9 (+https://example.org)"


# --- Typed records ---------------------------------------------------------


def test_f010_returns_typed_records_with_every_requested_field(tmp_path: Path) -> None:
    titan = _client(FakeAniList(), tmp_path).fetch_top_anime(1)[0]

    assert isinstance(titan, AniListAnime)
    assert titan.id == ATTACK_ON_TITAN
    assert titan.id_mal == 16498
    assert titan.title.romaji == "Shingeki no Kyojin"
    assert titan.title.english == "Attack on Titan"
    assert titan.title.native == "進撃の巨人"
    assert "AoT" in titan.synonyms
    assert titan.popularity == 1078245
    assert titan.average_score == 85
    assert (titan.start_date.year, titan.start_date.month, titan.start_date.day) == (2013, 4, 7)
    assert titan.end_date.year == 2013
    assert titan.status == "FINISHED"
    assert titan.format == "TV"
    assert titan.genres == ["Action", "Drama", "Fantasy", "Mystery"]


def test_f010_flattens_relations_studios_and_characters(tmp_path: Path) -> None:
    titan = _client(FakeAniList(), tmp_path).fetch_top_anime(1)[0]

    assert len(titan.relations) == 11
    adaptation = titan.relations[0]
    assert (adaptation.relation_type, adaptation.id, adaptation.type) == (
        "ADAPTATION",
        53390,
        "MANGA",
    )

    assert len(titan.studios) == 7
    wit = titan.studios[0]
    assert (wit.id, wit.name, wit.favourites) == (858, "WIT STUDIO", 12859)
    assert wit.is_main is True
    assert wit.is_animation_studio is True
    assert titan.studios[1].is_main is False

    eren = titan.characters[0]
    assert (eren.id, eren.role, eren.favourites) == (40882, "MAIN", 32069)
    assert eren.name.full == "Eren Yeager"
    assert eren.name.native == "エレン・イェーガー"
    assert "Eren Jaeger" in eren.name.alternative


def test_f010_accepts_missing_optional_fields() -> None:
    anime = AniListAnime.model_validate(
        {
            "id": 1,
            "idMal": None,
            "title": {"romaji": "X", "english": None, "native": None},
            "synonyms": [],
            "popularity": 5,
            "averageScore": None,
            "startDate": {"year": None, "month": None, "day": None},
            "endDate": {"year": None, "month": None, "day": None},
            "status": "NOT_YET_RELEASED",
            "format": None,
            "genres": [],
        }
    )

    assert anime.average_score is None
    assert anime.start_date.year is None
    assert anime.format is None
    assert anime.characters == []


# --- F-015: tags, source material and episode counts -------------------------


def test_f015_requests_tags_source_and_episodes(tmp_path: Path) -> None:
    api = FakeAniList()

    _client(api, tmp_path).fetch_top_anime(1)

    query = json.loads(api.requests[0].content)["query"]
    assert "tags { name rank isGeneralSpoiler isMediaSpoiler isAdult }" in query
    # Version 3 of the enum tells WEB_NOVEL, GAME, ... apart from OTHER.
    assert "source(version: 3)" in query
    assert "episodes" in query


def test_f015_returns_tags_source_and_episodes(tmp_path: Path) -> None:
    titan, slayer = _client(FakeAniList(), tmp_path).fetch_top_anime(2)

    assert (titan.source, titan.episodes) == ("MANGA", 25)
    assert (slayer.source, slayer.episodes) == ("MANGA", 26)

    assert len(titan.tags) == 29
    tags = {tag.name: tag for tag in titan.tags}
    kaiju = tags["Kaiju"]
    assert (kaiju.rank, kaiju.is_general_spoiler, kaiju.is_media_spoiler, kaiju.is_adult) == (
        93,
        False,
        False,
        False,
    )
    # Recorded data has both kinds of spoiler flag.
    assert tags["Time Skip"].is_general_spoiler is True
    assert tags["Time Skip"].is_media_spoiler is False
    assert tags["Henshin"].is_general_spoiler is False
    assert tags["Henshin"].is_media_spoiler is True


def test_f015_accepts_missing_tags_source_and_episodes() -> None:
    anime = AniListAnime.model_validate(
        {"id": 1, "title": {"romaji": "X"}, "tags": None, "source": None, "episodes": None}
    )

    assert anime.tags == []
    assert anime.source is None
    assert anime.episodes is None
