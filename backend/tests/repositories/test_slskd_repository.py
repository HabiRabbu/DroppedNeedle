"""SlskdRepository tests: protocol conformance, semaphore enforcement,
slskd JSON -> DownloadSearchResult translation, query building, path parsing,
and (username, filenames) status/cancel correlation."""

import asyncio
from pathlib import Path

import httpx
import pytest

from repositories.protocols.download_client import (
    DownloadClientProtocol,
    DownloadFileRef,
    TaskRef,
)
from repositories.slskd.slskd_client import SlskdClient
from repositories.slskd.slskd_models import (
    SlskdEnqueueResponse,
    SlskdFile,
    SlskdSearchResponse,
    SlskdUserSearchResponse,
)
from repositories.slskd.slskd_repository import SlskdRepository
from tests.mocks import slskd_mock


class _ConcFake:
    """Concurrency-tracking fake SlskdClient for semaphore tests."""

    def __init__(self) -> None:
        self.search_active = 0
        self.search_max = 0
        self.enqueue_active = 0
        self.enqueue_max = 0

    async def start_search(self, query, *, timeout_seconds=30.0):
        self.search_active += 1
        self.search_max = max(self.search_max, self.search_active)
        await asyncio.sleep(0.05)
        self.search_active -= 1
        return SlskdSearchResponse(id="s", is_complete=True)

    async def get_search_state(self, search_id):
        return SlskdSearchResponse(id=search_id, is_complete=True)

    async def get_search_responses(self, search_id):
        return []

    async def enqueue(self, username, files):
        self.enqueue_active += 1
        self.enqueue_max = max(self.enqueue_max, self.enqueue_active)
        await asyncio.sleep(0.05)
        self.enqueue_active -= 1
        return SlskdEnqueueResponse()

    async def get_downloads(self, username):
        return []

    async def cancel_transfer(self, username, transfer_id):
        return True

    async def health_check(self):
        return {"version": {"current": "0.25.1.0"}}


@pytest.fixture
def mock_repo() -> SlskdRepository:
    slskd_mock.reset_state()
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=slskd_mock.app))
    client = SlskdClient(http, "http://slskd", "test-key")
    return SlskdRepository(
        client=client, url="http://slskd", api_key="test-key", downloads_mount=Path("/dl")
    )


def test_is_instance_of_protocol(mock_repo):
    assert isinstance(mock_repo, DownloadClientProtocol)
    assert mock_repo.is_configured() is True


def test_is_configured_requires_url_and_key():
    repo = SlskdRepository(
        client=None, url="", api_key="", downloads_mount=Path("/dl")
    )
    assert repo.is_configured() is False


@pytest.mark.asyncio
async def test_search_semaphore_serializes():
    fake = _ConcFake()
    repo = SlskdRepository(
        client=fake, url="u", api_key="k", downloads_mount=Path("/dl"), concurrent_searches=1
    )
    await asyncio.gather(*(repo.search_album("A", f"Album {i}") for i in range(5)))
    assert fake.search_max == 1


@pytest.mark.asyncio
async def test_enqueue_semaphore_serializes_and_returns_taskref():
    fake = _ConcFake()
    repo = SlskdRepository(
        client=fake, url="u", api_key="k", downloads_mount=Path("/dl"), concurrent_enqueues=1
    )
    refs = await asyncio.gather(
        *(
            repo.enqueue([DownloadFileRef(username="alice", filename=f"f{i}.flac", size=10)])
            for i in range(5)
        )
    )
    assert fake.enqueue_max == 1
    assert all(isinstance(r, TaskRef) for r in refs)
    assert refs[0].username == "alice"
    assert refs[0].filenames == ["f0.flac"]


class _LaggedCompletionFake:
    """slskd surfaces /responses ONLY after the search completes, and completion
    lands AFTER the searchTimeout window. This fake reproduces that: the first
    `incomplete_polls` state checks report in-progress, then it completes."""

    def __init__(self, incomplete_polls, files):
        self._incomplete_polls = incomplete_polls
        self._files = files
        self.state_calls = 0

    async def start_search(self, query, *, timeout_seconds=30.0):
        return SlskdSearchResponse(id="s", is_complete=False)

    async def get_search_state(self, search_id):
        self.state_calls += 1
        return SlskdSearchResponse(id=search_id, is_complete=self.state_calls > self._incomplete_polls)

    async def get_search_responses(self, search_id):
        return self._files


@pytest.mark.asyncio
async def test_search_waits_for_completion_past_the_search_window():
    # Regression: slskd returns results only once the search completes, which is
    # AFTER the searchTimeout window. The old code used `timeout` for BOTH the
    # search window and the poll deadline, so it always gave up before slskd
    # surfaced anything -> 0 results on every search.
    files = [
        SlskdUserSearchResponse(
            username="alice",
            file_count=1,
            files=[SlskdFile(filename="Alice\\Album\\01.flac", size=1000)],
        )
    ]
    fake = _LaggedCompletionFake(incomplete_polls=2, files=files)
    repo = SlskdRepository(client=fake, url="u", api_key="k", downloads_mount=Path("/dl"))
    repo._COMPLETION_GRACE_SECONDS = 5.0  # bound the test if the fix regresses
    # timeout=0 -> the OLD deadline (now + timeout) would poll zero times. The fix
    # keeps polling through the grace window until the lagged completion.
    results = await repo.search_album("A", "Album", timeout=0.0)
    assert len(results) == 1
    assert results[0].username == "alice"
    assert fake.state_calls > 2  # proves it polled past the in-progress window


class _LadderFake:
    """Returns canned responses only for specific query strings, recording the
    order queries were tried - to test the escalating broad-search fallback."""

    def __init__(self, results_by_query):
        self._by_query = results_by_query
        self.queries = []
        self._last = ""

    async def start_search(self, query, *, timeout_seconds=30.0):
        self.queries.append(query)
        self._last = query
        return SlskdSearchResponse(id="s", is_complete=True)

    async def get_search_state(self, search_id):
        return SlskdSearchResponse(id=search_id, is_complete=True)

    async def get_search_responses(self, search_id):
        return self._by_query.get(self._last, [])


def _one_file(username="bob", filename="bob\\Folder\\01.flac"):
    return [SlskdUserSearchResponse(username=username, file_count=1, files=[SlskdFile(filename=filename, size=1)])]


def test_album_query_ladder_escalates_and_dedupes():
    with_year = SlskdRepository._album_query_ladder("Artist", "Album", 2000)
    assert with_year == ["Artist Album 2000", "Artist Album", "Artist"]
    # year=None collapses the first two rungs into one.
    no_year = SlskdRepository._album_query_ladder("Artist", "Album", None)
    assert no_year == ["Artist Album", "Artist"]


@pytest.mark.asyncio
async def test_search_album_stops_at_first_nonempty():
    q0 = SlskdRepository._build_album_query("Artist", "Album", 2000)
    fake = _LadderFake({q0: _one_file()})
    repo = SlskdRepository(client=fake, url="u", api_key="k", downloads_mount=Path("/dl"))
    results = await repo.search_album("Artist", "Album", 2000)
    assert len(results) == 1
    assert fake.queries == [q0]  # first rung had results -> no wasted broad search


@pytest.mark.asyncio
async def test_search_album_falls_back_to_broad_query_on_empty():
    # Only the broadest (artist-only) rung has results - the Aphex Twin case.
    fake = _LadderFake({"Aphex Twin": _one_file(filename="bob\\Aphex Twin\\SAW 85-92\\01.flac")})
    repo = SlskdRepository(client=fake, url="u", api_key="k", downloads_mount=Path("/dl"))
    results = await repo.search_album("Aphex Twin", "Selected Ambient Works 85-92", 1992)
    assert len(results) == 1
    assert fake.queries[0] == SlskdRepository._build_album_query("Aphex Twin", "Selected Ambient Works 85-92", 1992)
    assert fake.queries[-1] == "Aphex Twin"  # escalated all the way to artist-only
    assert len(fake.queries) == 3


@pytest.mark.asyncio
async def test_search_album_empty_when_whole_ladder_empty():
    fake = _LadderFake({})
    repo = SlskdRepository(client=fake, url="u", api_key="k", downloads_mount=Path("/dl"))
    assert await repo.search_album("Nobody", "Nothing", 1999) == []
    assert len(fake.queries) == 3  # exhausted the ladder before giving up


@pytest.mark.asyncio
async def test_search_track_keeps_title_and_does_not_go_artist_only():
    fake = _LadderFake({})
    repo = SlskdRepository(client=fake, url="u", api_key="k", downloads_mount=Path("/dl"))
    await repo.search_track("Artist", "Song", "Album")
    # two rungs, both keep the track title; never falls back to artist-only.
    assert fake.queries == ["Artist Song Album", "Artist Song"]


@pytest.mark.asyncio
async def test_search_album_translates_results(mock_repo):
    results = await mock_repo.search_album("Radiohead", "OK Computer", 1997, 12)
    alice = [r for r in results if r.username == "alice"]
    assert len(alice) == 12
    # extension parsed from filename even though slskd's field is empty (C6a).
    assert all(r.extension == "flac" for r in alice)
    # parent_directory parsed from a Windows-style path.
    assert alice[0].parent_directory == "Radiohead - OK Computer (1997)"
    # lossless: bitrate left None (C6b).
    assert alice[0].bitrate is None


@pytest.mark.asyncio
async def test_get_status_correlates_by_filename(mock_repo):
    ref = await mock_repo.enqueue(
        [DownloadFileRef(username="alice", filename="dir/a.flac", size=100)]
    )
    status = await mock_repo.get_status(ref)
    assert status.files_total == 1
    assert status.files_completed == 1
    assert status.status == "completed"


@pytest.mark.asyncio
async def test_cancel_removes_matching_transfers(mock_repo):
    ref = await mock_repo.enqueue(
        [DownloadFileRef(username="alice", filename="dir/a.flac", size=100)]
    )
    assert await mock_repo.cancel(ref) is True
    status = await mock_repo.get_status(ref)
    assert status.files_completed == 0


@pytest.mark.asyncio
async def test_get_file_path_resolves_slskd_leaf_folder_layout(tmp_path):
    # slskd writes {downloads}/{leaf remote folder}/{filename}; the remote filename
    # carries the FULL peer path but only the leaf folder survives on disk.
    leaf = tmp_path / "The Marías"
    leaf.mkdir()
    f = leaf / "The Marías - Nobody New.mp3"
    f.write_bytes(b"x")
    repo = SlskdRepository(client=None, url="", api_key="", downloads_mount=tmp_path)
    path = await repo.get_file_path(
        "alice", "@@peer\\Music\\The Marías\\The Marías - Nobody New.mp3"
    )
    assert path == f.resolve()


@pytest.mark.asyncio
async def test_get_file_path_flat_layout_fallback(tmp_path):
    f = tmp_path / "01 song.flac"
    f.write_bytes(b"x")
    repo = SlskdRepository(client=None, url="", api_key="", downloads_mount=tmp_path)
    path = await repo.get_file_path("alice", "Artist/Album/01 song.flac")
    assert path == f.resolve()


@pytest.mark.asyncio
async def test_get_file_path_scans_for_sanitised_folder(tmp_path):
    # slskd may rename the local folder; fall back to a one-level scan for the file.
    folder = tmp_path / "Artist - Album"
    folder.mkdir()
    f = folder / "02 song.flac"
    f.write_bytes(b"x")
    repo = SlskdRepository(client=None, url="", api_key="", downloads_mount=tmp_path)
    path = await repo.get_file_path("alice", "Some/Other/Remote/02 song.flac")
    assert path == f.resolve()


@pytest.mark.asyncio
async def test_get_file_path_missing_returns_none(tmp_path):
    repo = SlskdRepository(client=None, url="", api_key="", downloads_mount=tmp_path)
    assert await repo.get_file_path("alice", "Artist/Album/missing.flac") is None


@pytest.mark.asyncio
async def test_get_file_path_rejects_traversal(tmp_path):
    repo = SlskdRepository(client=None, url="", api_key="", downloads_mount=tmp_path)
    assert await repo.get_file_path("alice", "../../etc/passwd") is None


def test_parse_search_responses_windows_linux_and_disc():
    resp = SlskdUserSearchResponse(
        username="u",
        has_free_upload_slot=True,
        upload_speed=5,
        files=[
            SlskdFile(filename="Artist\\Album\\01 song.flac", size=1),
            SlskdFile(filename="Artist/Album/CD 2/05 song.flac", size=2),
        ],
    )
    out = SlskdRepository._parse_search_responses([resp])
    assert out[0].parent_directory == "Album"
    assert out[0].extension == "flac"
    # disc-pattern directory walked past to the album-level folder.
    assert out[1].parent_directory == "Album"


def test_sanitize_query_preserves_hyphenated_names():
    assert SlskdRepository._sanitize_query("AC-DC - Back in Black") == "AC-DC Back in Black"


def test_build_album_query_joins_with_separator():
    query = SlskdRepository._build_album_query("Radiohead", "OK Computer", 1997)
    assert query == "Radiohead OK Computer 1997"
