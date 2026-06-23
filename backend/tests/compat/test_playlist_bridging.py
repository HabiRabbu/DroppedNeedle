"""T0.9 - playlist bridging: library_file_id column + add_file_id_entry (Q11)."""

import threading
from pathlib import Path

import pytest

from core.exceptions import PermissionDeniedError, ResourceNotFoundError
from infrastructure.persistence.auth_store import UserRecord
from repositories.playlist_repository import PlaylistRepository
from services.playlist_service import PlaylistService

pytestmark = pytest.mark.asyncio

_ALICE = UserRecord(
    id="user-alice", display_name="Alice", role="user",
    created_at="2024-01-01T00:00:00Z", username="alice",
)
_BOB = UserRecord(
    id="user-bob", display_name="Bob", role="user",
    created_at="2024-01-01T00:00:00Z", username="bob",
)


@pytest.fixture
def playlist_service(
    db_path: Path, write_lock: threading.Lock, seeded_library, auth_store, tmp_path: Path
) -> PlaylistService:
    db, _lm, _ids = seeded_library
    repo = PlaylistRepository(db_path=db_path, write_lock=write_lock)
    return PlaylistService(
        repo=repo, cache_dir=tmp_path, auth_store=auth_store, library_db=db
    )


async def test_add_file_id_entry_populates_snapshot_and_link(
    playlist_service, seeded_library
):
    _db, _lm, ids = seeded_library
    pl = await playlist_service.create_playlist("My Mix", user_id="user-alice")
    entry = await playlist_service.add_file_id_entry(
        pl.id, ids["tracks"][0], requesting=_ALICE
    )
    assert entry.library_file_id == ids["tracks"][0]
    assert entry.track_source_id == ids["tracks"][0]
    assert entry.source_type == "droppedneedle-local"
    assert entry.track_name == "Airbag"
    assert entry.album_id == ids["rg"]
    assert entry.available_sources == ["droppedneedle-local"]


async def test_entry_persists_and_reads_back_with_link(playlist_service, seeded_library):
    _db, _lm, ids = seeded_library
    pl = await playlist_service.create_playlist("My Mix", user_id="user-alice")
    await playlist_service.add_file_id_entry(pl.id, ids["tracks"][0], requesting=_ALICE)
    await playlist_service.add_file_id_entry(pl.id, ids["tracks"][1], requesting=_ALICE)
    tracks = await playlist_service.get_tracks(pl.id)
    assert [t.library_file_id for t in tracks] == ids["tracks"]


async def test_legacy_entry_leaves_library_file_id_null(playlist_service):
    pl = await playlist_service.create_playlist("Legacy", user_id="user-alice")
    # a legacy/outbound-style entry added via the normal add_tracks path
    await playlist_service.add_tracks(
        pl.id, _ALICE,
        [{
            "track_name": "Old", "artist_name": "Artist", "album_name": "Album",
            "source_type": "plex", "track_source_id": "plex-key-1",
        }],
    )
    tracks = await playlist_service.get_tracks(pl.id)
    assert len(tracks) == 1
    assert tracks[0].library_file_id is None  # so compat listings can filter it out


async def test_add_file_id_entry_unknown_file_raises(playlist_service):
    pl = await playlist_service.create_playlist("X", user_id="user-alice")
    with pytest.raises(ResourceNotFoundError):
        await playlist_service.add_file_id_entry(pl.id, "no-such-file", requesting=_ALICE)


async def test_add_file_id_entry_enforces_ownership(playlist_service, seeded_library):
    _db, _lm, ids = seeded_library
    pl = await playlist_service.create_playlist("Alice only", user_id="user-alice")
    with pytest.raises(PermissionDeniedError):
        await playlist_service.add_file_id_entry(
            pl.id, ids["tracks"][0], requesting=_BOB
        )
