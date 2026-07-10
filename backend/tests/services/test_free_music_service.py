"""FreeMusicService: candidate ranking, the licence-only rule, download with
progress, cancel, retry, and the handoff to the import pipeline.

The Archive is stubbed with AsyncMock (house rule for metadata repos); the store
is a real SQLite file; downloads write real bytes into tmp_path.
"""

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ValidationError
from infrastructure.persistence.free_music_store import FreeMusicStore
from models.free_music import FreeMusicStatus
from repositories.archive_repository import ArchiveError, ArchiveFile, ArchiveItem
from services.native.free_music_service import FreeMusicService

CC = "http://creativecommons.org/licenses/by-nc-sa/3.0/"


def _item(identifier="jamendo-117853", title="Guess Who's a Mess") -> ArchiveItem:
    return ArchiveItem(identifier=identifier, title=title, creator="Brad Sucks", licence_url=CC)


def _files(fmt="VBR MP3", count=10, size=500) -> list[ArchiveFile]:
    return [
        ArchiveFile(name=f"{i:02d}.mp3", format=fmt, size_bytes=size, track=i, title=f"Song {i}")
        for i in range(1, count + 1)
    ]


def _build(tmp_path, *, items=None, files=None, preferred="mp3", enabled=True, sse=None):
    store = FreeMusicStore(tmp_path / "library.db", threading.Lock())
    archive = AsyncMock()
    archive.search_audio = AsyncMock(return_value=items if items is not None else [_item()])
    archive.get_item_files = AsyncMock(
        return_value=(CC, files if files is not None else _files())
    )
    archive.extension_for = MagicMock(
        side_effect=lambda f: {"vbr mp3": "mp3", "flac": "flac"}.get(f.lower(), "")
    )

    async def _stream(identifier, filename):
        yield b"audio-bytes"

    archive.stream_file = _stream

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    drop_import = MagicMock()
    drop_import.incoming_dir = lambda: incoming
    drop_import.create_job = AsyncMock()

    prefs = SimpleNamespace(
        get_free_music_settings=lambda: SimpleNamespace(
            enabled=enabled, preferred_format=preferred
        )
    )
    service = FreeMusicService(
        store=store,
        archive=archive,
        drop_import=drop_import,
        preferences_service=prefs,
        sse_publisher=sse or AsyncMock(),
    )
    return service, store, archive, drop_import


async def _settle(service, store, task_id):
    for _ in range(2000):
        task = await store.get(task_id)
        if task and task.status in FreeMusicStatus.TERMINAL:
            return task
        await asyncio.sleep(0)
    raise AssertionError(f"task never settled: {(await store.get(task_id)).status}")


# -- the happy path --


@pytest.mark.asyncio
async def test_album_request_downloads_and_hands_off_to_the_importer(tmp_path):
    service, store, _, drop_import = _build(tmp_path)

    task_id = await service.request_album(
        user_id="u1",
        release_group_mbid="d0484284-1ee7-4157-951a-50f003cbcfb4",
        artist_name="Brad Sucks",
        album_title="Guess Who's a Mess",
    )
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.COMPLETED
    assert task.identifier == "jamendo-117853"
    assert task.licence_url == CC
    assert task.files_total == 10 and task.files_completed == 10

    drop_import.create_job.assert_awaited_once()
    uploads = drop_import.create_job.await_args.kwargs["uploads"]
    assert len(uploads) == 10
    assert all(Path(p).name.endswith(".mp3") for _n, p in uploads)


@pytest.mark.asyncio
async def test_progress_events_carry_the_status(tmp_path):
    """The frontend sweeps its library caches only when status == 'completed', so a
    missing or wrong status silently leaves stale grids after a download lands."""
    sse = AsyncMock()
    service, store, _, _ = _build(tmp_path, sse=sse)

    task_id = await service.request_album(
        user_id="u1",
        release_group_mbid="d0484284-1ee7-4157-951a-50f003cbcfb4",
        artist_name="Brad Sucks",
        album_title="Guess Who's a Mess",
    )
    await _settle(service, store, task_id)

    published = [call.args for call in sse.publish.await_args_list]
    assert all(channel == "user:u1" for channel, _event, _payload in published)
    assert all(event == "free_music_updated" for _channel, event, _payload in published)

    statuses = [payload["status"] for _channel, _event, payload in published]
    assert statuses[-1] == FreeMusicStatus.COMPLETED
    assert statuses.count(FreeMusicStatus.COMPLETED) == 1
    assert FreeMusicStatus.IMPORTING in statuses
    assert all(payload["task_id"] == task_id for _c, _e, payload in published)


@pytest.mark.asyncio
async def test_a_failure_publishes_a_failed_status(tmp_path):
    sse = AsyncMock()
    service, store, _, _ = _build(tmp_path, items=[], sse=sse)

    task_id = await service.request_album(
        user_id="u1",
        release_group_mbid="rg",
        artist_name="Nobody",
        album_title="Nothing",
    )
    await _settle(service, store, task_id)

    statuses = [call.args[2]["status"] for call in sse.publish.await_args_list]
    assert statuses[-1] == FreeMusicStatus.FAILED


@pytest.mark.asyncio
async def test_staging_is_removed_after_a_successful_import(tmp_path):
    service, store, _, _ = _build(tmp_path)
    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    await _settle(service, store, task_id)

    assert not (tmp_path / "incoming" / f"free-{task_id}").exists()


# -- the licence-only rule --


@pytest.mark.asyncio
async def test_an_item_whose_licence_cannot_be_read_is_never_downloaded(tmp_path):
    """`a-new-low-in-hifi` is a real CC album with no licenseurl. Free Music
    must not touch it - the repository reports ('', []) and there is no candidate."""
    service, store, archive, drop_import = _build(tmp_path)
    archive.get_item_files = AsyncMock(return_value=("", []))

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="A New Low in Hi-Fi"
    )
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.FAILED
    assert "No source has this" in (task.error or "")
    drop_import.create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_title_that_does_not_resemble_the_request_is_rejected(tmp_path):
    """The Archive is full of tributes and remasters by the same artist."""
    service, store, _, drop_import = _build(
        tmp_path, items=[_item(identifier="tribute", title="Piano Tribute to Brad Sucks")]
    )

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.FAILED
    drop_import.create_job.assert_not_awaited()


# -- ranking --


@pytest.mark.asyncio
async def test_preferred_format_wins(tmp_path):
    both = _files("VBR MP3", 10) + _files("FLAC", 10, size=5000)
    service, store, _, _ = _build(tmp_path, files=both, preferred="flac")

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    task = await _settle(service, store, task_id)
    assert task.format == "flac"


@pytest.mark.asyncio
async def test_track_count_agreement_beats_format_preference(tmp_path):
    """A 10-track MusicBrainz album should not pull a 2-track FMA sampler."""
    sampler = _files("FLAC", 2, size=5000)
    full = _files("VBR MP3", 10)
    service, store, archive, _ = _build(tmp_path, files=sampler + full, preferred="flac")

    task_id = await service.request_album(
        user_id="u1",
        release_group_mbid="rg",
        artist_name="Brad Sucks",
        album_title="Guess Who's a Mess",
        track_count=10,
    )
    task = await _settle(service, store, task_id)
    assert task.format == "mp3"
    assert task.files_total == 10


# -- failures, cancel, retry --


@pytest.mark.asyncio
async def test_a_dead_archive_fails_the_task_with_a_readable_error(tmp_path):
    service, store, archive, _ = _build(tmp_path)
    archive.search_audio = AsyncMock(side_effect=ArchiveError("boom"))

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="A", album_title="B"
    )
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.FAILED
    assert "Internet Archive" in (task.error or "")


@pytest.mark.asyncio
async def test_download_retries_once_then_fails(tmp_path):
    service, store, archive, drop_import = _build(tmp_path)
    attempts = {"n": 0}

    async def _flaky(identifier, filename):
        attempts["n"] += 1
        raise OSError("connection reset")
        yield b""  # pragma: no cover - generator shape

    archive.stream_file = _flaky

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.FAILED
    assert attempts["n"] == 2  # one retry, then give up
    assert not (tmp_path / "incoming" / f"free-{task_id}").exists()
    drop_import.create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_stops_the_download_and_cleans_up(tmp_path):
    service, store, archive, drop_import = _build(tmp_path)
    started = asyncio.Event()

    async def _slow(identifier, filename):
        started.set()
        await asyncio.sleep(0.05)
        yield b"x"

    archive.stream_file = _slow

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    await service.cancel(task_id, user_id="u1", is_admin=False)

    for _ in range(200):
        if not (tmp_path / "incoming" / f"free-{task_id}").exists():
            break
        await asyncio.sleep(0.01)

    task = await store.get(task_id)
    assert task.status == FreeMusicStatus.CANCELLED
    drop_import.create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_rejects_a_finished_task(tmp_path):
    service, store, _, _ = _build(tmp_path)
    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    await _settle(service, store, task_id)

    with pytest.raises(ValidationError):
        await service.cancel(task_id, user_id="u1", is_admin=False)


@pytest.mark.asyncio
async def test_a_non_owner_cannot_see_or_cancel_a_task(tmp_path):
    from core.exceptions import ResourceNotFoundError

    service, store, _, _ = _build(tmp_path)
    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    await _settle(service, store, task_id)

    with pytest.raises(ResourceNotFoundError):
        await service.get_task(task_id, user_id="intruder", is_admin=False)
    # an admin may
    assert await service.get_task(task_id, user_id="intruder", is_admin=True)


@pytest.mark.asyncio
async def test_retry_reruns_a_failed_task(tmp_path):
    service, store, archive, drop_import = _build(tmp_path)
    archive.search_audio = AsyncMock(side_effect=ArchiveError("down"))

    task_id = await service.request_album(
        user_id="u1", release_group_mbid="rg", artist_name="Brad Sucks", album_title="Guess Who's a Mess"
    )
    await _settle(service, store, task_id)

    archive.search_audio = AsyncMock(return_value=[_item()])
    await service.retry(task_id, user_id="u1", is_admin=False)
    task = await _settle(service, store, task_id)

    assert task.status == FreeMusicStatus.COMPLETED
    drop_import.create_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_free_music_refuses_a_request(tmp_path):
    service, _, _, _ = _build(tmp_path, enabled=False)
    assert service.is_ready() is False
    with pytest.raises(ValidationError):
        await service.request_album(
            user_id="u1", release_group_mbid="rg", artist_name="A", album_title="B"
        )


@pytest.mark.asyncio
async def test_sweep_stale_fails_an_interrupted_task(tmp_path):
    service, store, _, _ = _build(tmp_path)
    await store.create("orphan", "u1", "album", "rg", "A", "B")

    await service.sweep_stale()

    assert (await store.get("orphan")).status == FreeMusicStatus.FAILED
