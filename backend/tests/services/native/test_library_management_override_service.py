import sqlite3
import threading
from pathlib import Path

import pytest

from core.exceptions import ResourceNotFoundError, StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_management_override_service import (
    LibraryManagementOverrideService,
)


def _store(tmp_path: Path) -> tuple[NativeLibraryStore, Path]:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO auth_users(id) VALUES ('admin')")
    store = NativeLibraryStore(path, threading.Lock())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, normalized_name, kind, created_at, updated_at) "
            "VALUES ('artist-1', 'Artist', 'artist', 'artist', 'person', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, updated_at) "
            "VALUES ('album-1', 'root-1', 'group-1', 'Album', 'album', 'Artist', "
            "'artist', 'artist-1', 'automatic', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_tracks "
            "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
            "file_size_bytes, file_mtime_ns, stat_revision, stat_revision_kind, "
            "title, title_folded, album_title, album_title_folded, disc_number, "
            "track_number, file_format, ingest_source, imported_at, membership_source) "
            "VALUES ('track-1', 'album-1', 'root-1', '/music/track.flac', "
            "'track.flac', 'path', 10, 10, 'stat', 'exact', 'Track', 'track', "
            "'Album', 'album', 1, 1, 'flac', 'scan', 1, 'automatic')"
        )
    return store, path


@pytest.mark.asyncio
async def test_override_crud_validates_value_scope_and_revisions(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    service = LibraryManagementOverrideService(store, clock=lambda: 10.0)

    created = await service.save(
        subject_kind="track",
        subject_id="track-1",
        subject_revision=1,
        field_name="artist",
        mode="replace",
        value=["Artist A", "artist a", "Artist B"],
        actor_user_id="admin",
    )
    assert created.value_json == '["Artist A","Artist B"]'
    assert created.subject_revision == 1
    assert created.row_revision == 1

    updated = await service.save(
        subject_kind="track",
        subject_id="track-1",
        subject_revision=1,
        field_name="artist",
        mode="preserve",
        override_id=created.id,
        expected_row_revision=1,
    )
    assert updated.mode == "preserve"
    assert updated.row_revision == 2

    with pytest.raises(StaleRevisionError):
        await service.save(
            subject_kind="track",
            subject_id="track-1",
            subject_revision=1,
            field_name="artist",
            mode="clear",
            override_id=created.id,
            expected_row_revision=1,
        )
    with pytest.raises(ValidationError, match="album-level"):
        await service.save(
            subject_kind="track",
            subject_id="track-1",
            subject_revision=1,
            field_name="album",
            mode="replace",
            value="Wrong scope",
        )
    with pytest.raises(ValidationError, match="list"):
        await service.save(
            subject_kind="track",
            subject_id="track-1",
            subject_revision=1,
            field_name="artist",
            mode="replace",
            value="Not a list",
        )


@pytest.mark.asyncio
async def test_override_subject_revision_is_checked_in_store_transaction(
    tmp_path: Path,
) -> None:
    store, path = _store(tmp_path)
    service = LibraryManagementOverrideService(store, clock=lambda: 10.0)
    created = await service.save(
        subject_kind="track",
        subject_id="track-1",
        subject_revision=1,
        field_name="title",
        mode="replace",
        value="Title",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE local_tracks SET row_revision = 2 WHERE id = 'track-1'"
        )

    with pytest.raises(StaleRevisionError, match="subject changed"):
        await service.save(
            subject_kind="track",
            subject_id="track-1",
            subject_revision=1,
            field_name="title",
            mode="replace",
            value="Changed",
            override_id=created.id,
            expected_row_revision=1,
        )


@pytest.mark.asyncio
async def test_reset_is_subject_bound_and_compare_and_swap_protected(
    tmp_path: Path,
) -> None:
    store, _ = _store(tmp_path)
    service = LibraryManagementOverrideService(store, clock=lambda: 10.0)
    created = await service.save(
        subject_kind="album",
        subject_id="album-1",
        subject_revision=1,
        field_name="album",
        mode="clear",
    )
    values, revision = await service.list_for_subject(
        subject_kind="album", subject_id="album-1"
    )
    assert values == [created]
    assert len(revision) == 64

    with pytest.raises(ResourceNotFoundError):
        await service.reset(
            override_id=created.id,
            subject_kind="album",
            subject_id="another-album",
            expected_row_revision=1,
        )
    with pytest.raises(StaleRevisionError):
        await service.reset(
            override_id=created.id,
            subject_kind="album",
            subject_id="album-1",
            expected_row_revision=2,
        )

    await service.reset(
        override_id=created.id,
        subject_kind="album",
        subject_id="album-1",
        expected_row_revision=1,
    )
    values, changed_revision = await service.list_for_subject(
        subject_kind="album", subject_id="album-1"
    )
    assert values == []
    assert changed_revision != revision
