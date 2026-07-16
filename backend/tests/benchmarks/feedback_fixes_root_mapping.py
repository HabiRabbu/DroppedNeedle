"""Generated production-shaped typed-root migration and mapping rehearsal."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import tempfile
import threading
from pathlib import Path

import msgspec

from core.config import Settings
from infrastructure.persistence.library_db import LibraryDB
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.library_policy_service import LibraryPolicyService
from services.preferences_service import PreferencesService


async def rehearse() -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix="feedback-fixes-root-mapping-"
    ) as directory:
        workspace = Path(directory)
        root = workspace / "Music"
        root.mkdir()
        config_path = workspace / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "library_settings": {
                        "library_paths": [str(root)],
                        "staging_path": "",
                        "naming_template": "{title}.{ext}",
                        "acoustid_api_key": "",
                    }
                }
            ),
            encoding="utf-8",
        )
        settings = Settings()
        settings.config_file_path = config_path
        preferences = PreferencesService(settings)
        first = preferences.get_typed_library_settings()
        first_config = config_path.read_text(encoding="utf-8")
        second = preferences.get_typed_library_settings()

        database = LibraryDB(workspace / "library.db", threading.Lock())
        with sqlite3.connect(database.db_path) as connection:
            connection.executemany(
                "INSERT INTO library_files "
                "(id, track_number, track_title, album_title, file_path, "
                "file_size_bytes, file_mtime, file_format, source, confidence, imported_at) "
                "VALUES (?, 1, 'Track', 'Album', ?, 1, 1, 'flac', "
                "'manual_review', 1, 1)",
                [
                    (
                        f"file-{index}",
                        str(root / "Artist" / f"Album-{index}" / "01.flac"),
                    )
                    for index in range(60)
                ],
            )
            connection.executemany(
                "INSERT INTO manual_review_queue (file_path, source, created_at) "
                "VALUES (?, 'text_match', 1)",
                [(str(root / "Loose" / f"track-{index}.flac"),) for index in range(40)],
            )
            connection.commit()

        resolver = LibraryPolicyResolver(preferences.get_typed_library_settings())
        service = LibraryPolicyService(
            preferences,
            database,
            resolver_getter=lambda: resolver,
            resolver_clearer=lambda: None,
        )
        database_hash_before = hashlib.sha256(database.db_path.read_bytes()).hexdigest()
        report = await service.dry_run_path_mapping()
        service.require_catalog_import_mapping(report)
        database_hash_after = hashlib.sha256(database.db_path.read_bytes()).hexdigest()
        return {
            "schema": "feedback-fixes-root-mapping-v1",
            "legacy_path_count": 1,
            "typed_root_count": len(first.library_roots),
            "root_ids_stable": first.library_roots[0].id == second.library_roots[0].id,
            "migration_idempotent": first_config
            == config_path.read_text(encoding="utf-8"),
            "source_database_unchanged_by_dry_run": database_hash_before
            == database_hash_after,
            "report": msgspec.to_builtins(report),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(rehearse())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
