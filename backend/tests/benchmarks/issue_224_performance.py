"""Non-default scale rehearsal for GitHub issue #224."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
import threading
from pathlib import Path
from time import perf_counter

from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_ownership_service import (
    AlbumOwnershipCandidate,
    LibraryOwnershipService,
)


def _seed(
    database: Path, *, artists: int, albums: int, tracks: int
) -> NativeLibraryStore:
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    store = NativeLibraryStore(database, threading.Lock())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, 'person', 1, 1)",
            ((f"artist-{i}", f"Artist {i}", f"artist {i}") for i in range(artists)),
        )
        connection.executemany(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, updated_at) "
            "VALUES (?, 'root', ?, ?, ?, ?, ?, ?, 'automatic', 1, 1)",
            (
                (
                    f"album-{i}",
                    f"group-{i}",
                    f"Album {i}",
                    f"album {i}",
                    f"Artist {i % artists}",
                    f"artist {i % artists}",
                    f"artist-{i % artists}",
                )
                for i in range(albums)
            ),
        )
        connection.executemany(
            "INSERT INTO local_album_artists "
            "(local_album_id, position, local_artist_id, role) VALUES (?, 0, ?, 'primary')",
            ((f"album-{i}", f"artist-{i % artists}") for i in range(albums)),
        )
        connection.executemany(
            "INSERT INTO local_album_external_identities "
            "(local_album_id, provider, release_group_mbid, decision_source, selected_at) "
            "VALUES (?, 'musicbrainz', ?, 'automatic', 1)",
            ((f"album-{i}", f"rg-{i}") for i in range(albums)),
        )
        connection.executemany(
            "INSERT INTO local_tracks "
            "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
            "file_size_bytes, file_mtime_ns, stat_revision, title, title_folded, "
            "album_title, album_title_folded, file_format, ingest_source, imported_at, "
            "membership_source) VALUES (?, ?, 'root', ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, "
            "'flac', 'benchmark', 1, 'automatic')",
            (
                (
                    f"track-{i}",
                    f"album-{i % albums}",
                    f"/music/track-{i}.flac",
                    f"track-{i}.flac",
                    f"hash-{i}",
                    f"stat-{i}",
                    f"Track {i}",
                    f"track {i}",
                    f"Album {i % albums}",
                    f"album {i % albums}",
                )
                for i in range(tracks)
            ),
        )
    return store


async def run(*, artists: int, albums: int, tracks: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="droppedneedle-issue-224-") as scratch:
        store = _seed(
            Path(scratch) / "catalog.db",
            artists=artists,
            albums=albums,
            tracks=tracks,
        )
        ownership = LibraryOwnershipService(store)
        started = perf_counter()
        snapshot = await store.target_provider_album_snapshot()
        snapshot_seconds = perf_counter() - started
        candidates = [
            AlbumOwnershipCandidate(
                release_group_mbid=f"rg-{i}",
                title=f"Album {i}",
                album_artist=f"Artist {i % artists}",
            )
            for i in range(min(200, albums))
        ]
        started = perf_counter()
        projected = await ownership.project_albums(candidates)
        projection_seconds = perf_counter() - started
        store._provider_album_snapshot = None
        started = perf_counter()
        concurrent = await asyncio.gather(
            *(store.target_provider_album_snapshot() for _ in range(7))
        )
        concurrent_seconds = perf_counter() - started
        return {
            "cardinality": {"artists": artists, "albums": albums, "tracks": tracks},
            "snapshot_ids": len(snapshot[1]),
            "projected_candidates": len(projected),
            "owned_candidates": sum(item.owned for item in projected),
            "concurrent_snapshot_results": len(concurrent),
            "seconds": {
                "snapshot": round(snapshot_seconds, 4),
                "project_200": round(projection_seconds, 4),
                "seven_coalesced_snapshots": round(concurrent_seconds, 4),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artists", type=int, default=1_445)
    parser.add_argument("--albums", type=int, default=30_911)
    parser.add_argument("--tracks", type=int, default=239_738)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run(artists=args.artists, albums=args.albums, tracks=args.tracks)
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
