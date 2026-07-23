import json
import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.audio import AudioArtistCredit, AudioInfo, AudioTag
from models.library_work import ScanRun
from models.local_catalog import LocalTrackGenre
from services.native.library_indexer import LibraryIndexer


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    return path


def _seed_scalar_catalog(path: Path) -> None:
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
            "file_size_bytes, file_mtime_ns, stat_revision, tag_revision, title, "
            "title_folded, artist_name, artist_name_folded, album_title, "
            "album_title_folded, album_artist_name, album_artist_name_folded, "
            "genre, genre_folded, file_format, ingest_source, imported_at, membership_source) "
            "VALUES ('track-1', 'album-1', 'root-1', '/music/track.flac', "
            "'track.flac', 'path-1', 10, 10, 'stat-1', 'tag-1', 'Track', "
            "'track', 'Artist', 'artist', 'Album', 'album', 'Artist', 'artist', "
            "'Rock; Pop', 'rock; pop', 'flac', 'scan', 1, 'automatic')"
        )
        connection.execute(
            "INSERT INTO local_track_artists "
            "(local_track_id, position, local_artist_id, role, credited_name) "
            "VALUES ('track-1', 0, 'artist-1', 'primary', 'Artist')"
        )


def test_scalar_genre_migration_preserves_one_opaque_value_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    NativeLibraryStore(path, threading.Lock())
    _seed_scalar_catalog(path)

    NativeLibraryStore(path, threading.Lock())
    NativeLibraryStore(path, threading.Lock())

    with sqlite3.connect(path) as connection:
        genres = connection.execute(
            "SELECT position, name, folded_name, source "
            "FROM local_track_genres WHERE local_track_id = 'track-1'"
        ).fetchall()
        credit = connection.execute(
            "SELECT credited_name, join_phrase FROM local_track_artists "
            "WHERE local_track_id = 'track-1'"
        ).fetchone()

    assert genres == [(0, "Rock; Pop", "rock; pop", "local")]
    assert credit == ("Artist", "")


def test_legacy_scalar_updates_sync_only_unambiguous_local_genre_projection(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    NativeLibraryStore(path, threading.Lock())
    _seed_scalar_catalog(path)
    NativeLibraryStore(path, threading.Lock())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE local_tracks SET genre = 'Jazz', genre_folded = 'jazz' "
            "WHERE id = 'track-1'"
        )
        synced = connection.execute(
            "SELECT position, name, folded_name, source FROM local_track_genres "
            "WHERE local_track_id = 'track-1' ORDER BY position"
        ).fetchall()
        connection.execute(
            "INSERT INTO local_track_genres "
            "(local_track_id, position, name, folded_name, source) "
            "VALUES ('track-1', 1, 'Soul', 'soul', 'local')"
        )
        connection.execute(
            "UPDATE local_tracks SET genre = 'Metal', genre_folded = 'metal' "
            "WHERE id = 'track-1'"
        )
        protected = connection.execute(
            "SELECT position, name, folded_name, source FROM local_track_genres "
            "WHERE local_track_id = 'track-1' ORDER BY position"
        ).fetchall()
        connection.execute(
            "DELETE FROM local_track_genres WHERE local_track_id = 'track-1'"
        )
        connection.execute(
            "INSERT INTO local_track_genres "
            "(local_track_id, position, name, folded_name, source) "
            "VALUES ('track-1', 0, 'Ambient', 'ambient', 'musicbrainz')"
        )
        connection.execute(
            "UPDATE local_tracks SET genre = 'Country', genre_folded = 'country' "
            "WHERE id = 'track-1'"
        )
        provider_owned = connection.execute(
            "SELECT position, name, folded_name, source FROM local_track_genres "
            "WHERE local_track_id = 'track-1' ORDER BY position"
        ).fetchall()

    assert synced == [(0, "Jazz", "jazz", "local")]
    assert protected == [
        (0, "Jazz", "jazz", "local"),
        (1, "Soul", "soul", "local"),
    ]
    assert provider_owned == [(0, "Ambient", "ambient", "musicbrainz")]


@pytest.mark.asyncio
async def test_scan_persists_native_genres_and_all_known_artist_credits_without_duplicates(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    store = NativeLibraryStore(path, threading.Lock())
    await store.create_scan_run(
        ScanRun(
            id="scan-1",
            kind="incremental",
            trigger="manual",
            state="indexing",
            phase="indexing",
            queued_at=1,
            updated_at=1,
        )
    )
    indexer = LibraryIndexer(store, object())
    tag = AudioTag(
        title="Track",
        artist="Artist A feat. Artist B",
        album="Album",
        album_artist="Album Artist",
        track_number=1,
        genre="Rock; Jazz",
        genres=["Rock", "Jazz"],
        album_artists=[AudioArtistCredit(name="Album Artist")],
        artists=[
            AudioArtistCredit(name="Artist A", join_phrase=" feat. "),
            AudioArtistCredit(name="Artist B"),
        ],
    )
    info = AudioInfo(
        duration_seconds=180,
        bitrate=900,
        sample_rate=44_100,
        channels=2,
        file_format="flac",
        file_size_bytes=100,
        bit_depth=16,
    )
    item = {
        "root_id": "root-1",
        "relative_path": "Album/track.flac",
        "absolute_path": "/music/Album/track.flac",
        "local_track_id": None,
        "file_size_bytes": 100,
        "file_mtime_ns": 1_000_000_000,
        "stat_revision": "stat-1",
        "policy_revision": "policy-1",
        "effective_policy": "automatic",
        "comparison_result": "new",
    }
    write = indexer._prepare_tagged("scan-1", item, tag, info)
    increments = {
        "inspected_count": 1,
        "new_count": 1,
        "changed_count": 0,
        "indexed_count": 1,
        "unchanged_count": 0,
        "excluded_count": 0,
        "errored_count": 0,
    }

    await store.commit_scan_index_batch(
        "scan-1",
        writes=[write],
        states={},
        failures=[],
        increments=increments,
        updated_at=2,
    )
    await store.commit_scan_index_batch(
        "scan-1",
        writes=[write],
        states={},
        failures=[],
        increments=increments,
        updated_at=3,
    )

    genres = await store.list_track_genres(write.track.id)
    credits = await store.list_track_artist_credits(write.track.id)
    album_credits = await store.list_album_artist_credits(write.album.id)
    genre_rows = await store.list_target_genres()
    projected = await store.get_target_track(write.track.id)

    assert [(genre.position, genre.name) for genre in genres] == [
        (0, "Rock"),
        (1, "Jazz"),
    ]
    assert [credit["display_name"] for credit in credits] == [
        "Artist A",
        "Artist B",
    ]
    assert [credit["join_phrase"] for credit in credits] == [" feat. ", ""]
    assert [credit["display_name"] for credit in album_credits] == ["Album Artist"]
    assert genre_rows == [
        {"genre": "Jazz", "song_count": 1, "album_count": 1},
        {"genre": "Rock", "song_count": 1, "album_count": 1},
    ]
    assert projected is not None
    assert json.loads(projected["genres_json"]) == ["Rock", "Jazz"]
    assert len(json.loads(projected["artist_credits_json"])) == 2
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM local_track_genres WHERE local_track_id = ?",
                (write.track.id,),
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM local_track_artists WHERE local_track_id = ?",
                (write.track.id,),
            ).fetchone()[0]
            == 2
        )


@pytest.mark.asyncio
async def test_secondary_genre_participates_in_browse_and_artwork_revisions(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    store = NativeLibraryStore(path, threading.Lock())
    _seed_scalar_catalog(path)
    await store.replace_track_genres(
        "track-1",
        [
            store_genre("track-1", 0, "Rock"),
            store_genre("track-1", 1, "Jazz"),
        ],
        expected_track_revision=1,
    )
    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT value FROM library_genre_artwork_revisions "
            "WHERE genre_folded = 'jazz'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO local_album_artwork "
            "(local_album_id, cover_url, source, updated_at) "
            "VALUES ('album-1', '/cover', 'manual', 2)"
        )
        after = connection.execute(
            "SELECT value FROM library_genre_artwork_revisions "
            "WHERE genre_folded = 'jazz'"
        ).fetchone()[0]

    albums = await store.get_target_albums_by_genre("Jazz", limit=10)
    tracks, total = await store.list_target_tracks(genre="Jazz")

    assert after > before
    assert [album["local_id"] for album in albums] == ["album-1"]
    assert [track["id"] for track in tracks] == ["track-1"]
    assert total == 1


def store_genre(track_id: str, position: int, name: str) -> LocalTrackGenre:
    return LocalTrackGenre(
        local_track_id=track_id,
        position=position,
        name=name,
        folded_name=name.casefold(),
        source="local",
    )
