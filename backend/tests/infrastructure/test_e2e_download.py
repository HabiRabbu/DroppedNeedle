"""E2E gate: search -> match -> enqueue -> poll -> process -> import -> library_files row.

A stub download client returns realistic results that the real scorer/matcher score;
everything else (DownloadStore, LibraryDB, AudioTagger, FileProcessor, orchestrator) is
real. The real-slskd container E2E is the Phase 9 gate (task-059).
"""

import shutil
import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.audio.tagger import AudioTagger
from infrastructure.persistence.download_store import DownloadStore
from infrastructure.persistence.library_db import LibraryDB
from infrastructure.persistence.request_history import RequestHistoryStore
from infrastructure.sse_publisher import SSEPublisher
from models.common import ServiceStatus
from models.download import DownloadSearchResult
from models.download_manifest import ManifestCodec
from repositories.protocols.download_client import DownloadTaskStatus, TaskRef
from services.native.album_preflight_scorer import AlbumPreflightScorer
from services.native.download_orchestrator import DownloadOrchestrator
from services.native.download_service import DownloadService
from services.native.file_processor import FileProcessor
from services.native.library_manager import LibraryManager
from services.native.naming import NamingTemplateEngine
from services.native.track_matcher import TrackMatcher
from services.request_service import RequestService

FIXTURE_FLAC = Path(__file__).resolve().parent.parent / "fixtures" / "library" / "flac_full_01.flac"
_TEMPLATE = "{albumartist}/{album} ({year})/{disc:02d}{track:02d} {title}.{ext}"


def _seed_auth_users(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT, role TEXT)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO auth_users (id, username, role) VALUES (?, ?, ?)",
            ("user-a", "alice", "admin"),
        )
        conn.commit()
    finally:
        conn.close()


class _StubClient:
    def __init__(self, downloads_root: Path, album=None, track=None) -> None:
        self._root = downloads_root
        self._album = album or []
        self._track = track or []
        self.cancelled: list[TaskRef] = []

    @property
    def client_name(self) -> str:
        return "stub"

    def is_configured(self) -> bool:
        return True

    async def health_check(self) -> ServiceStatus:
        return ServiceStatus(status="ok")

    async def search_album(self, artist, album, year=None, track_count=None, *, timeout=30.0):
        return list(self._album)

    async def search_track(self, artist, track, album=None, duration_seconds=None, *, timeout=30.0):
        return list(self._track)

    async def enqueue(self, files):
        return TaskRef(username=files[0].username, filenames=[f.filename for f in files])

    async def get_status(self, task_ref: TaskRef) -> DownloadTaskStatus:
        n = len(task_ref.filenames)
        return DownloadTaskStatus(
            task_id="", status="completed", files_total=n, files_completed=n,
            bytes_total=0, bytes_downloaded=0, progress_percent=100.0,
        )

    async def cancel(self, task_ref: TaskRef) -> bool:
        self.cancelled.append(task_ref)
        return True

    async def get_file_path(self, username: str, remote_filename: str):
        return self._root / remote_filename.replace("\\", "/").lstrip("/")


def _place_fixture(downloads_root: Path, rel: str) -> DownloadSearchResult:
    dest = downloads_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_FLAC, dest)
    parent = rel.rsplit("/", 1)[0]
    return DownloadSearchResult(
        username="peer1",
        filename=rel,
        parent_directory=parent,
        size=dest.stat().st_size,
        extension="flac",
        bitrate=1000,
        has_free_slot=True,
        upload_speed=5_000_000,
    )


def _build(tmp_path: Path, *, album=None, track=None):
    downloads = tmp_path / "slskd_downloads"
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    for p in (downloads, library, staging):
        p.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    store = DownloadStore(db_path=db_path, write_lock=lock)
    _seed_auth_users(db_path)
    library_db = LibraryDB(db_path=tmp_path / "library_files.db", write_lock=threading.Lock())
    manager = LibraryManager(library_db)
    client = _StubClient(downloads, album=album, track=track)

    fp = FileProcessor(
        AudioTagger(),
        naming_engine=NamingTemplateEngine(),
        library_manager=manager,
        library_paths=[library],
        client=client,
        slskd_downloads_path=downloads,
        fingerprinter=None,
        verify_downloads=False,
    )
    orch = DownloadOrchestrator(
        client=client,
        download_store=store,
        file_processor=fp,
        library_manager=manager,
        scorer=AlbumPreflightScorer(store, quality_min="low", flac_mp3_only=False),
        track_matcher=TrackMatcher(store, quality_min="low", flac_mp3_only=False),
        manifest_codec=ManifestCodec(),
        event_bus=SSEPublisher(),
        staging_path=staging,
        naming_template=_TEMPLATE,
        poll_interval=0.0,
        auto_accept_threshold=0.5,
        manual_threshold=0.1,
    )
    return store, manager, orch, client, library


@pytest.mark.asyncio
async def test_full_download_to_library(tmp_path: Path):
    album = [_place_fixture(tmp_path / "slskd_downloads", "Radiohead - OK Computer/01 Airbag.flac")]
    store, manager, orch, client, library = _build(tmp_path, album=album)

    task = await store.create_task(
        user_id="user-a",
        download_type="album",
        release_group_mbid="rg-okc",
        artist_name="Radiohead",
        album_title="OK Computer",
        year=1997,
        track_count=1,
    )

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final is not None
    assert final.status == "completed"
    assert await manager.has_album("rg-okc") is True
    flacs = list(library.rglob("*.flac"))
    assert len(flacs) == 1
    tag, _info = AudioTagger().read_tags(flacs[0])
    assert tag.album == "OK Computer"
    assert tag.musicbrainz_release_group_id == "rg-okc"
    # successful import clears the slskd transfer records
    assert len(client.cancelled) == 1


@pytest.mark.asyncio
async def test_track_request_to_library(tmp_path: Path):
    track = [_place_fixture(tmp_path / "slskd_downloads", "Radiohead - OK Computer/Airbag.flac")]
    store, manager, orch, client, library = _build(tmp_path, track=track)

    task = await store.create_task(
        user_id="user-a",
        download_type="track",
        release_group_mbid="rg-okc-track",
        recording_mbid="rec-airbag",
        artist_name="Radiohead",
        album_title="OK Computer",
        track_title="Airbag",
        year=1997,
        track_count=1,
    )

    await orch.process_task(task.id)

    final = await store.get_task(task.id)
    assert final is not None
    assert final.status == "completed"
    flacs = list(library.rglob("*.flac"))
    assert len(flacs) == 1
    assert await manager.has_album("rg-okc-track") is True


@pytest.mark.asyncio
async def test_request_links_download_task_id(tmp_path: Path):
    """RequestService auto-approve creates a real download task and links its id to
    request_history. Orchestrator dispatch is stubbed for determinism."""
    album = [_place_fixture(tmp_path / "slskd_downloads", "Radiohead - OK Computer/01 Airbag.flac")]
    store, manager, _orch, client, _library = _build(tmp_path, album=album)

    history = RequestHistoryStore(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    no_op_orch = MagicMock()
    no_op_orch.dispatch = MagicMock()
    download_service = DownloadService(
        client, AlbumPreflightScorer(store, quality_min="low", flac_mp3_only=False), manager, store,
        SSEPublisher(), no_op_orch,
    )
    request_service = RequestService(history, download_service)

    resp = await request_service.request_album(
        "rg-okc", artist="Radiohead", album="OK Computer", year=1997,
        user_id="user-a", user_role="admin",
    )
    assert resp.success is True

    record = await history.async_get_record("rg-okc")
    assert record is not None
    assert record.download_task_id is not None
    linked = await store.get_task(record.download_task_id)
    assert linked is not None
    assert linked.release_group_mbid == "rg-okc"
    no_op_orch.dispatch.assert_called_once()
