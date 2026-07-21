from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import sqlite3
import tempfile
import threading
from math import ceil
from pathlib import Path
from time import perf_counter

_IMPORT_ROOT: tempfile.TemporaryDirectory[str] | None = None
if "ROOT_APP_DIR" not in os.environ:
    _IMPORT_ROOT = tempfile.TemporaryDirectory(
        prefix="feedback-fixes-million-validation-import-"
    )
    os.environ["ROOT_APP_DIR"] = _IMPORT_ROOT.name

from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.target_startup_validator import TargetStartupValidator

_BATCH_SIZE = 10_000


def _seed_catalog(
    database: Path, *, file_count: int, review_count: int
) -> dict[str, float]:
    if file_count < 1_000_000:
        raise ValueError("The million-row rehearsal requires at least 1,000,000 files.")
    if review_count < 0 or review_count > file_count:
        raise ValueError("Review count must be between zero and the file count.")

    started = perf_counter()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, normalized_name, kind, created_at, updated_at) "
            "VALUES ('scale-artist', 'Scale Artist', 'scale artist', "
            "'scale artist', 'person', 1, 1)"
        )
        album_count = ceil(file_count / 1_000)
        connection.executemany(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    f"album-{index:07d}",
                    "root-1",
                    f"group-{index:07d}",
                    f"Scale Album {index}",
                    f"scale album {index}",
                    "Scale Artist",
                    "scale artist",
                    "scale-artist",
                    "legacy_import",
                    1,
                    1,
                )
                for index in range(album_count)
            ),
        )
        connection.execute(
            "INSERT INTO library_migration_runs "
            "(id, source_revision, root_revision, state, report_json, started_at, "
            "updated_at, completed_at) VALUES "
            "('million-scale', 'source-revision', 'root-revision', 'completed', "
            "'{}', 1, 2, 2)"
        )
        connection.execute(
            "UPDATE library_catalog_revision SET value = 1 WHERE singleton = 1"
        )
        connection.execute(
            "INSERT INTO library_migration_markers "
            "(marker, source_revision, target_catalog_revision, created_at) VALUES "
            "('legacy_catalog_import_complete', 'source-revision', 1, 2)"
        )
        connection.execute(
            "INSERT INTO library_migration_provenance "
            "(source_kind, source_key, target_kind, target_id, source_revision, "
            "imported_at, migration_run_id) VALUES "
            "('root', 'root-1', 'library_root', 'root-1', 'source-revision', 2, "
            "'million-scale')"
        )
        connection.commit()

        for batch_start in range(0, file_count, _BATCH_SIZE):
            batch_end = min(batch_start + _BATCH_SIZE, file_count)
            connection.executemany(
                "INSERT INTO local_tracks "
                "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
                "file_size_bytes, file_mtime_ns, stat_revision, title, title_folded, "
                "artist_name, artist_name_folded, album_title, album_title_folded, "
                "disc_number, track_number, file_format, ingest_source, imported_at, "
                "membership_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (
                        f"track-{index:08d}",
                        f"album-{index // 1_000:07d}",
                        "root-1",
                        f"/music/{index // 1_000:07d}/{index:08d}.flac",
                        f"{index // 1_000:07d}/{index:08d}.flac",
                        f"hash-{index:08d}",
                        8_000_000,
                        index + 1,
                        f"stat-{index:08d}",
                        f"Scale Track {index}",
                        f"scale track {index}",
                        "Scale Artist",
                        "scale artist",
                        f"Scale Album {index // 1_000}",
                        f"scale album {index // 1_000}",
                        1,
                        index % 1_000 + 1,
                        "flac",
                        "legacy_import",
                        2,
                        "legacy_import",
                    )
                    for index in range(batch_start, batch_end)
                ),
            )
            connection.executemany(
                "INSERT INTO library_migration_provenance "
                "(source_kind, source_key, target_kind, target_id, source_revision, "
                "imported_at, migration_run_id) VALUES (?,?,?,?,?,?,?)",
                (
                    (
                        "library_file",
                        f"track-{index:08d}",
                        "local_track",
                        f"track-{index:08d}",
                        "source-revision",
                        2,
                        "million-scale",
                    )
                    for index in range(batch_start, batch_end)
                ),
            )
            connection.commit()
            if batch_end % 100_000 == 0 or batch_end == file_count:
                print(
                    f"[scale] Seeded tracks: {batch_end:,}/{file_count:,}.", flush=True
                )

        for batch_start in range(0, review_count, _BATCH_SIZE):
            batch_end = min(batch_start + _BATCH_SIZE, review_count)
            connection.executemany(
                "INSERT INTO library_identification_reviews "
                "(id, local_track_id, state, reason_code, input_revision, created_at, "
                "updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    (
                        f"review-{index:08d}",
                        f"track-{index:08d}",
                        "needs_review",
                        "legacy_missing_release_group_id",
                        f"input-{index:08d}",
                        2,
                        2,
                    )
                    for index in range(batch_start, batch_end)
                ),
            )
            connection.executemany(
                "INSERT INTO library_migration_provenance "
                "(source_kind, source_key, target_kind, target_id, source_revision, "
                "imported_at, migration_run_id) VALUES (?,?,?,?,?,?,?)",
                (
                    (
                        "review_row",
                        f"review-{index:08d}",
                        "local_track",
                        f"track-{index:08d}",
                        "source-revision",
                        2,
                        "million-scale",
                    )
                    for index in range(batch_start, batch_end)
                ),
            )
            connection.commit()
            if batch_end % 100_000 == 0 or batch_end == review_count:
                print(
                    f"[scale] Seeded reviews: {batch_end:,}/{review_count:,}.",
                    flush=True,
                )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"seed_seconds": perf_counter() - started}


async def run(
    output: Path, *, file_count: int = 1_000_000, review_count: int | None = None
) -> dict[str, object]:
    effective_review_count = file_count if review_count is None else review_count
    started = perf_counter()
    with tempfile.TemporaryDirectory(
        prefix="feedback-fixes-million-validation-"
    ) as directory:
        database = Path(directory) / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        store = await asyncio.to_thread(NativeLibraryStore, database, threading.Lock())
        seed = await asyncio.to_thread(
            _seed_catalog,
            database,
            file_count=file_count,
            review_count=effective_review_count,
        )

        review_plan = await store.explain_query_plan(
            "SELECT 1 FROM library_identification_reviews "
            "WHERE local_track_id = ? AND reason_code LIKE 'legacy_%'",
            ("track",),
        )
        queue_plan = await store.explain_query_plan(
            "SELECT 1 FROM library_compat_play_queue_items "
            "WHERE user_id = SUBSTR(?, 1, INSTR(?, ':') - 1) "
            "AND item_index = CAST(SUBSTR(?, INSTR(?, ':') + 1) AS INTEGER) "
            "AND ? = user_id || ':' || item_index AND local_track_id = ?",
            ("user:0", "user:0", "user:0", "user:0", "user:0", "track"),
        )

        cutover_started = perf_counter()
        cutover = await TargetStartupValidator(
            store,
            lambda: {"root-1"},
            emit_progress=lambda message: print(f"[scale] {message}", flush=True),
        ).validate("cutover")
        cutover_seconds = perf_counter() - cutover_started

        admission_started = perf_counter()
        admission = await TargetStartupValidator(
            NativeLibraryStore(database, threading.Lock()),
            lambda: {"root-1"},
        ).validate("admission")
        admission_seconds = perf_counter() - admission_started

        passed = (
            all(value == 0 for value in cutover["invariants"].values())
            and all(value == 0 for value in admission["invariants"].values())
            and any("idx_library_reviews_track_reason" in row for row in review_plan)
            and any(
                "sqlite_autoindex_library_compat_play_queue_items_1" in row
                for row in queue_plan
            )
        )
        report: dict[str, object] = {
            "passed": passed,
            "file_count": file_count,
            "review_count": effective_review_count,
            "migration_provenance_count": file_count + effective_review_count + 1,
            "database_bytes": database.stat().st_size,
            "seed_seconds": seed["seed_seconds"],
            "cutover_validation_seconds": cutover_seconds,
            "admission_validation_seconds": admission_seconds,
            "cutover_invariants": cutover["invariants"],
            "admission_invariants": admission["invariants"],
            "review_query_plan": review_plan,
            "queue_query_plan": queue_plan,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "elapsed_seconds": perf_counter() - started,
        }
        if not passed:
            raise RuntimeError("The million-row startup validation rehearsal failed.")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--file-count", type=int, default=1_000_000)
    parser.add_argument("--review-count", type=int)
    args = parser.parse_args()
    report = asyncio.run(
        run(
            args.output,
            file_count=args.file_count,
            review_count=args.review_count,
        )
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
