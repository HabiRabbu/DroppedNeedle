"""DownloadService tests: library check, search pipeline, pick/cancel ownership +
bounds (domain exceptions), and the downloads-mount health check."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import (
    ConfigurationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)
from core.task_registry import TaskRegistry
from models.download import DownloadTask, ScoredCandidate, SearchJob
from repositories.protocols.download_client import DownloadSearchResult
from services.native.download_service import (
    ALREADY_IN_LIBRARY,
    DownloadService,
    check_downloads_mount,
)


def _candidate() -> ScoredCandidate:
    return ScoredCandidate(
        username="alice",
        parent_directory="A - B",
        files=[
            DownloadSearchResult(
                username="alice", filename="A - B/01.flac", parent_directory="A - B",
                size=1, extension="flac",
            )
        ],
        coherence=0.9,
        file_confidence=0.85,
        final_score=0.88,
        tier="auto",
    )


def _make_service(owner_id="u1", *, in_library=False, enabled=True):
    client = AsyncMock()
    client.search_album.return_value = []
    scorer = AsyncMock()
    scorer.rank.return_value = [_candidate()]
    library = AsyncMock()
    library.has_album.return_value = in_library
    store = AsyncMock()
    store.create_search_job.return_value = SearchJob(
        id="job1", user_id=owner_id, artist_name="A", album_title="B"
    )
    store.get_search_job.return_value = SearchJob(
        id="job1", user_id=owner_id, artist_name="A", album_title="B", release_group_mbid="rg"
    )
    store.get_search_job_candidates.return_value = [_candidate()]
    store.create_task.return_value = DownloadTask(id="task1", user_id=owner_id)
    bus = AsyncMock()
    # dispatch() is sync (returns an asyncio.Task); cancel/retry are async
    orchestrator = MagicMock()
    orchestrator.cancel_task = AsyncMock()
    orchestrator.retry_task = AsyncMock(return_value="task-retry")
    service = DownloadService(client, scorer, library, store, bus, orchestrator, enabled=enabled)
    return service, store, bus, client, scorer, orchestrator


@pytest.mark.asyncio
async def test_disabled_client_blocks_every_download_entry_point():
    # When the download client is disabled in Settings, no path may start a
    # download - including retry_task, which re-dispatches a fresh task.
    service, store, _bus, _client, _scorer, orchestrator = _make_service(enabled=False)
    calls = [
        lambda: service.search_album("u1", "A", "B", release_group_mbid="rg"),
        lambda: service.request_album("u1", "rg", "A", "B"),
        lambda: service.request_track("u1", "rec", "A", "Track"),
        lambda: service.pick_candidate("u1", "job1", 0),
        lambda: service.retry_task("task1", "u1", "user"),
    ]
    for make in calls:
        with pytest.raises(ConfigurationError):
            await make()
    store.create_task.assert_not_called()
    orchestrator.retry_task.assert_not_called()


@pytest.mark.asyncio
async def test_search_album_already_in_library():
    service, store, *_ = _make_service(in_library=True)
    result = await service.search_album("u1", "A", "B", release_group_mbid="rg")
    assert result == ALREADY_IN_LIBRARY
    store.create_search_job.assert_not_called()


@pytest.mark.asyncio
async def test_search_album_creates_job_and_runs_search():
    service, store, bus, *_ = _make_service()
    job_id = await service.search_album("u1", "A", "B", release_group_mbid="rg")
    assert job_id == "job1"
    store.create_search_job.assert_called_once()
    # Await the registered background search deterministically (no wall-clock sleep).
    await TaskRegistry.get_instance().get_all()["search-job1"]
    store.set_search_job_candidates.assert_awaited_once()
    store.update_search_job_status.assert_any_await("job1", "completed")
    # SSE emits a 'searching' status event, then a 'complete' event with the payload.
    events = {call.args[1]: call.args[2] for call in bus.publish.await_args_list}
    assert events["status"] == {"status": "searching"}
    assert events["complete"]["candidate_count"] == 1
    assert events["complete"]["top_score"] == _candidate().final_score


@pytest.mark.asyncio
async def test_run_search_failure_marks_failed():
    service, store, bus, client, _, _ = _make_service()
    client.search_album.side_effect = RuntimeError("boom")
    await service._run_search("job1", "A", "B", None, 12)
    store.update_search_job_status.assert_any_await("job1", "failed", error="search failed")


@pytest.mark.asyncio
async def test_pick_candidate_creates_queued_task_and_matches():
    service, store, *_ = _make_service()
    task_id = await service.pick_candidate("u1", "job1", 0)
    assert task_id == "task1"
    store.create_task.assert_awaited_once()
    kwargs = store.create_task.await_args.kwargs
    assert kwargs["status"] == "queued"
    assert kwargs["source_username"] == "alice"
    assert kwargs["search_job_id"] == "job1"
    assert kwargs["candidate_index"] == 0
    store.update_search_job_status.assert_any_await("job1", "matched")


@pytest.mark.asyncio
async def test_pick_candidate_non_owner_raises_permission_denied():
    service, *_ = _make_service(owner_id="someone-else")
    with pytest.raises(PermissionDeniedError):
        await service.pick_candidate("u1", "job1", 0)


@pytest.mark.asyncio
async def test_pick_candidate_bad_index_raises_validation_error():
    service, *_ = _make_service()
    with pytest.raises(ValidationError):
        await service.pick_candidate("u1", "job1", 5)
    with pytest.raises(ValidationError):
        await service.pick_candidate("u1", "job1", -1)


@pytest.mark.asyncio
async def test_pick_candidate_missing_job_raises_not_found():
    service, store, *_ = _make_service()
    store.get_search_job.return_value = None
    with pytest.raises(ResourceNotFoundError):
        await service.pick_candidate("u1", "job1", 0)


@pytest.mark.asyncio
async def test_cancel_search_owner():
    service, store, *_ = _make_service()
    assert await service.cancel_search("u1", "job1") is True
    store.update_search_job_status.assert_any_await("job1", "cancelled")


@pytest.mark.asyncio
async def test_cancel_search_non_owner_raises():
    service, *_ = _make_service(owner_id="someone-else")
    with pytest.raises(PermissionDeniedError):
        await service.cancel_search("u1", "job1")


def _make_service_with_mb(owner_id="u1"):
    """A service wired with a MusicBrainz matcher + repo for request_track tests."""
    service, store, bus, client, scorer, orchestrator = _make_service(owner_id)
    matcher = MagicMock()
    matcher.resolve_recording_to_release_group = AsyncMock(return_value="rg-x")
    mb = MagicMock()
    mb.get_release_group = AsyncMock(
        return_value=SimpleNamespace(title="Resolved Album", artist_name="Resolved Artist", year=2001)
    )
    service._matcher = matcher
    service._mb = mb
    return service, store, client, orchestrator, matcher, mb


@pytest.mark.asyncio
async def test_request_album_already_in_library():
    service, store, *_ = _make_service(in_library=True)
    result = await service.request_album("u1", "rg", "A", "B")
    assert result == ALREADY_IN_LIBRARY
    store.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_request_album_dedup_returns_existing_task():
    service, store, _bus, _client, _scorer, orchestrator = _make_service()
    store.get_active_task_for_album.return_value = DownloadTask(id="existing", user_id="u1")
    result = await service.request_album("u1", "rg", "A", "B")
    assert result == "existing"
    store.create_task.assert_not_called()
    orchestrator.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_request_album_creates_task_and_dispatches():
    service, store, _bus, _client, _scorer, orchestrator = _make_service()
    store.get_active_task_for_album.return_value = None
    store.create_task.return_value = DownloadTask(id="new-task", user_id="u1")
    result = await service.request_album("u1", "rg", "Artist", "Album", year=1999)
    assert result == "new-task"
    store.create_task.assert_awaited_once()
    orchestrator.dispatch.assert_called_once_with("new-task")


@pytest.mark.asyncio
async def test_request_album_backfills_year_when_missing():
    # A compact request button sends no year; the service backfills it from the
    # release group so the album folder isn't created as "Album ()".
    service, store, _client, _orchestrator, _matcher, mb = _make_service_with_mb()
    store.get_active_task_for_album.return_value = None

    await service.request_album("u1", "rg", "Radiohead", "OK Computer")  # year omitted

    mb.get_release_group.assert_awaited_once_with("rg")
    assert store.create_task.await_args.kwargs["year"] == 2001  # from the mb stub


@pytest.mark.asyncio
async def test_request_album_year_backfill_failure_still_creates_task():
    # The year is a nicety: a MusicBrainz failure must not fail the download.
    service, store, _client, _orchestrator, _matcher, mb = _make_service_with_mb()
    store.get_active_task_for_album.return_value = None
    mb.get_release_group = AsyncMock(side_effect=RuntimeError("MB down"))

    result = await service.request_album("u1", "rg", "Radiohead", "OK Computer")

    assert result == "task1"  # request still succeeded
    assert store.create_task.await_args.kwargs["year"] is None  # degraded gracefully


@pytest.mark.asyncio
async def test_request_track_already_in_library():
    service, store, _bus, _client, _scorer, orchestrator = _make_service()
    service._library.has_track.return_value = True
    result = await service.request_track("u1", "rec-1", "Artist", "Track")
    assert result == ALREADY_IN_LIBRARY
    store.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_request_track_without_resolver_raises_validation():
    # _make_service has matcher=None; an unresolved release group is a 400.
    service, _store, _bus, _client, _scorer, _orch = _make_service()
    service._library.has_track.return_value = False
    with pytest.raises(ValidationError):
        await service.request_track("u1", "rec-1", "Artist", "Track")


@pytest.mark.asyncio
async def test_request_track_resolves_and_creates_track_task():
    service, store, _client, orchestrator, matcher, mb = _make_service_with_mb()
    service._library.has_track.return_value = False
    store.get_active_task_for_track.return_value = None
    store.create_task.return_value = DownloadTask(id="track-task", user_id="u1")

    result = await service.request_track("u1", "rec-1", "", "Airbag", duration_seconds=212)

    assert result == "track-task"
    matcher.resolve_recording_to_release_group.assert_awaited_once_with("rec-1")
    mb.get_release_group.assert_awaited_once_with("rg-x")
    kwargs = store.create_task.await_args.kwargs
    assert kwargs["download_type"] == "track"
    assert kwargs["track_count"] == 1
    assert kwargs["recording_mbid"] == "rec-1"
    assert kwargs["track_title"] == "Airbag"
    # the user-supplied duration is threaded onto the task for TrackMatcher
    assert kwargs["track_duration_seconds"] == 212
    orchestrator.dispatch.assert_called_once_with("track-task")


@pytest.mark.asyncio
async def test_request_track_dedup_is_recording_keyed_not_album_keyed():
    # A second, different track of the same album must NOT be swallowed by the
    # album-keyed dedup: track tasks dedup on the recording.
    service, store, _client, orchestrator, _matcher, _mb = _make_service_with_mb()
    service._library.has_track.return_value = False
    store.get_active_task_for_track.return_value = None
    store.get_active_task_for_album.return_value = DownloadTask(id="album-active", user_id="u1")
    store.create_task.return_value = DownloadTask(id="track-task", user_id="u1")

    result = await service.request_track("u1", "rec-2", "Artist", "Lucky", release_group_mbid="rg-x")

    assert result == "track-task"
    store.get_active_task_for_track.assert_awaited_once_with("rec-2", "u1")
    store.get_active_task_for_album.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_task_delegates_to_orchestrator():
    service, _store, _bus, _client, _scorer, orchestrator = _make_service()
    await service.cancel_task("t1", "u1", "user")
    orchestrator.cancel_task.assert_awaited_once_with("t1", "u1", "user")


@pytest.mark.asyncio
async def test_retry_task_delegates_to_orchestrator():
    service, _store, _bus, _client, _scorer, orchestrator = _make_service()
    result = await service.retry_task("t1", "u1", "user")
    assert result == "task-retry"
    orchestrator.retry_task.assert_awaited_once_with("t1", "u1", "user")


def test_mount_not_set():
    assert check_downloads_mount(None, []).reason == "not_set"
    assert check_downloads_mount("", []).reason == "not_set"


def test_mount_missing(tmp_path):
    status = check_downloads_mount(tmp_path / "nope", [tmp_path])
    assert status.ok is False
    assert status.reason == "missing"


def test_mount_ok(tmp_path):
    downloads = tmp_path / "dl"
    downloads.mkdir()
    status = check_downloads_mount(downloads, [tmp_path])
    assert status.ok is True
    assert status.reason == "ok"


def test_mount_not_writable(tmp_path, monkeypatch):
    downloads = tmp_path / "dl"
    downloads.mkdir()
    monkeypatch.setattr("services.native.download_service.os.access", lambda p, m: False)
    status = check_downloads_mount(downloads, [tmp_path])
    assert status.ok is False
    assert status.reason == "not_writable"


def test_mount_different_filesystem(tmp_path, monkeypatch):
    downloads = tmp_path / "dl"
    downloads.mkdir()
    library = tmp_path / "lib"
    library.mkdir()

    class _FakeStat:
        def __init__(self, dev):
            self.st_dev = dev

    def fake_stat(self, *args, **kwargs):
        return _FakeStat(1 if self == downloads else 2)

    monkeypatch.setattr(Path, "stat", fake_stat)
    status = check_downloads_mount(downloads, [library])
    assert status.ok is False
    assert status.reason == "different_filesystem"
