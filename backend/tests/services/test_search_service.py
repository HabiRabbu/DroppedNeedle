import pytest
from unittest.mock import AsyncMock, MagicMock
import asyncio
from types import SimpleNamespace

from api.v1.schemas.search import SearchResult, SuggestResponse
from services.search_service import SearchService


def _make_search_result(
    type: str,
    title: str,
    score: int = 0,
    musicbrainz_id: str = "",
    artist: str | None = None,
    year: int | None = None,
    disambiguation: str | None = None,
) -> SearchResult:
    return SearchResult(
        type=type,
        title=title,
        musicbrainz_id=musicbrainz_id or f"mbid-{title.lower().replace(' ', '-')}",
        score=score,
        artist=artist,
        year=year,
        disambiguation=disambiguation,
        in_library=False,
        requested=False,
    )


def _make_preferences(
    secondary_types: list[str] | None = None,
    primary_types: list[str] | None = None,
) -> MagicMock:
    prefs = MagicMock()
    prefs.secondary_types = secondary_types or []
    prefs.primary_types = primary_types or [
        "album",
        "single",
        "ep",
        "broadcast",
        "other",
    ]
    return prefs


def _make_service(
    grouped: dict[str, list[SearchResult]] | None = None,
    library_mbids: set[str] | None = None,
    mb_error: Exception | None = None,
    library_error: Exception | None = None,
) -> SearchService:
    mb_repo = MagicMock()
    if mb_error:
        mb_repo.search_grouped = AsyncMock(side_effect=mb_error)
    else:
        mb_repo.search_grouped = AsyncMock(
            return_value=grouped or {"artists": [], "albums": []}
        )

    library_repo = MagicMock()
    if library_error:
        library_repo.get_library_mbids = AsyncMock(side_effect=library_error)
    else:
        library_repo.get_library_mbids = AsyncMock(return_value=library_mbids or set())

    coverart_repo = MagicMock()
    preferences_service = MagicMock()
    preferences_service.get_preferences.return_value = _make_preferences()

    return SearchService(
        mb_repo=mb_repo,
        library_repo=library_repo,
        coverart_repo=coverart_repo,
        preferences_service=preferences_service,
    )


@pytest.mark.asyncio
async def test_suggest_returns_suggest_response():
    artists = [_make_search_result("artist", "Muse", score=90)]
    albums = [
        _make_search_result("album", "Origin of Symmetry", score=85, artist="Muse")
    ]
    svc = _make_service(grouped={"artists": artists, "albums": albums})

    result = await svc.suggest(query="muse", limit=5)

    assert isinstance(result, SuggestResponse)
    assert len(result.results) == 2
    assert result.results[0].title == "Muse"
    assert result.results[1].title == "Origin of Symmetry"


@pytest.mark.asyncio
async def test_target_suggest_projects_only_returned_albums() -> None:
    album = _make_search_result(
        "album", "Origin of Symmetry", artist="Muse", musicbrainz_id="rg-1"
    )
    service = _make_service(grouped={"artists": [], "albums": [album]})
    ownership = AsyncMock()
    ownership.project_albums.return_value = [SimpleNamespace(owned=True)]
    service._ownership = ownership

    result = await service.suggest(query="muse", limit=5)

    assert result.results[0].in_library is True
    service._library_repo.get_library_mbids.assert_not_awaited()
    candidates = ownership.project_albums.await_args.args[0]
    assert [candidate.release_group_mbid for candidate in candidates] == ["rg-1"]


@pytest.mark.asyncio
async def test_suggest_score_interleaving():
    artists = [
        _make_search_result("artist", "Artist A", score=90),
        _make_search_result("artist", "Artist B", score=80),
    ]
    albums = [
        _make_search_result("album", "Album X", score=95, artist="X"),
        _make_search_result("album", "Album Y", score=85, artist="Y"),
    ]
    svc = _make_service(grouped={"artists": artists, "albums": albums})

    result = await svc.suggest(query="test", limit=5)

    assert len(result.results) == 4
    assert result.results[0].title == "Album X"
    assert result.results[0].score == 95
    assert result.results[1].title == "Artist A"
    assert result.results[1].score == 90
    assert result.results[2].title == "Album Y"
    assert result.results[2].score == 85
    assert result.results[3].title == "Artist B"
    assert result.results[3].score == 80


@pytest.mark.asyncio
async def test_suggest_equal_score_artist_before_album():
    artists = [_make_search_result("artist", "Bee", score=80)]
    albums = [_make_search_result("album", "Ant", score=80, artist="Someone")]
    svc = _make_service(grouped={"artists": artists, "albums": albums})

    result = await svc.suggest(query="test", limit=5)

    assert len(result.results) == 2
    assert result.results[0].type == "artist"
    assert result.results[0].title == "Bee"
    assert result.results[1].type == "album"
    assert result.results[1].title == "Ant"


@pytest.mark.asyncio
async def test_suggest_alphabetical_tiebreak_within_same_type():
    artists = [
        _make_search_result("artist", "Zebra", score=80),
        _make_search_result("artist", "Alpha", score=80),
    ]
    svc = _make_service(grouped={"artists": artists, "albums": []})

    result = await svc.suggest(query="test", limit=5)

    assert len(result.results) == 2
    assert result.results[0].title == "Alpha"
    assert result.results[1].title == "Zebra"


@pytest.mark.asyncio
async def test_suggest_truncates_to_limit():
    artists = [
        _make_search_result("artist", f"Artist {i}", score=100 - i) for i in range(3)
    ]
    albums = [
        _make_search_result("album", f"Album {i}", score=99 - i, artist="X")
        for i in range(3)
    ]
    svc = _make_service(grouped={"artists": artists, "albums": albums})

    result = await svc.suggest(query="test", limit=4)

    assert len(result.results) == 4


@pytest.mark.asyncio
async def test_suggest_library_failure_returns_default_flags():
    artists = [_make_search_result("artist", "Muse", score=90)]
    albums = [
        _make_search_result(
            "album", "Absolution", score=85, artist="Muse", musicbrainz_id="album-1"
        ),
    ]
    svc = _make_service(
        grouped={"artists": artists, "albums": albums},
        library_error=Exception("library unavailable"),
    )

    result = await svc.suggest(query="muse", limit=5)

    assert len(result.results) == 2
    for r in result.results:
        assert r.in_library is False
        assert r.requested is False


@pytest.mark.asyncio
async def test_suggest_musicbrainz_failure_returns_empty():
    svc = _make_service(mb_error=Exception("MusicBrainz down"))

    result = await svc.suggest(query="muse", limit=5)

    assert isinstance(result, SuggestResponse)
    assert len(result.results) == 0


@pytest.mark.asyncio
async def test_suggest_query_normalization():
    artists = [_make_search_result("artist", "Muse", score=90)]
    svc = _make_service(grouped={"artists": artists, "albums": []})

    result = await svc.suggest(query="  muse  ", limit=5)

    assert len(result.results) == 1
    assert result.results[0].title == "Muse"
    svc._mb_repo.search_grouped.assert_called_once()
    call_args = svc._mb_repo.search_grouped.call_args
    assert call_args[0][0] == "muse"


@pytest.mark.asyncio
async def test_suggest_in_library_flag():
    albums = [
        _make_search_result(
            "album", "Absolution", score=85, artist="Muse", musicbrainz_id="album-lib-1"
        ),
    ]
    svc = _make_service(
        grouped={"artists": [], "albums": albums},
        library_mbids={"album-lib-1"},
    )

    result = await svc.suggest(query="absolution", limit=5)

    assert len(result.results) == 1
    assert result.results[0].in_library is True
    assert result.results[0].requested is False


@pytest.mark.asyncio
async def test_suggest_whitespace_only_query_returns_empty():
    svc = _make_service(grouped={"artists": [], "albums": []})

    result = await svc.suggest(query="  a  ", limit=5)

    assert isinstance(result, SuggestResponse)
    assert len(result.results) == 0
    svc._mb_repo.search_grouped.assert_not_called()


@pytest.mark.asyncio
async def test_suggest_single_char_after_strip_returns_empty():
    svc = _make_service(grouped={"artists": [], "albums": []})

    result = await svc.suggest(query="x", limit=5)

    assert isinstance(result, SuggestResponse)
    assert len(result.results) == 0
    svc._mb_repo.search_grouped.assert_not_called()


@pytest.mark.asyncio
async def test_suggest_case_insensitive_alphabetical_tiebreak():
    artists = [
        _make_search_result("artist", "Bravo", score=80),
        _make_search_result("artist", "alpha", score=80),
    ]
    svc = _make_service(grouped={"artists": artists, "albums": []})

    result = await svc.suggest(query="test", limit=5)

    assert len(result.results) == 2
    assert result.results[0].title == "alpha"
    assert result.results[1].title == "Bravo"


@pytest.mark.asyncio
async def test_suggest_deduplication_single_mb_call():
    artists = [_make_search_result("artist", "Muse", score=90)]

    call_event = asyncio.Event()
    call_count = 0

    async def slow_search_grouped(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await call_event.wait()
        return {"artists": artists, "albums": []}

    mb_repo = MagicMock()
    mb_repo.search_grouped = slow_search_grouped

    library_repo = MagicMock()
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    library_repo.get_queue = AsyncMock(return_value=[])

    coverart_repo = MagicMock()
    preferences_service = MagicMock()
    preferences_service.get_preferences.return_value = _make_preferences()

    svc = SearchService(
        mb_repo=mb_repo,
        library_repo=library_repo,
        coverart_repo=coverart_repo,
        preferences_service=preferences_service,
    )

    task1 = asyncio.create_task(svc.suggest(query="muse", limit=5))
    task2 = asyncio.create_task(svc.suggest(query="muse", limit=5))
    await asyncio.sleep(0.05)
    call_event.set()

    r1, r2 = await asyncio.gather(task1, task2)

    assert call_count == 1
    assert len(r1.results) == 1
    assert len(r2.results) == 1
