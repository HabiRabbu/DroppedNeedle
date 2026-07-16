import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from infrastructure.persistence.maintenance_manifest import (
    MaintenanceManifestError,
    capture_source_identity,
    capture_complete_manifest,
    restore_complete_manifest,
    restore_complete_manifest_in_place,
    validate_complete_manifest,
)


_REPOSITORY_ROOT = Path(__file__).parents[3]


def _prior_application() -> dict[str, object]:
    return {
        "container_id": "container-before-cutover",
        "image_id": "sha256:" + "a" * 64,
        "rollback_image_reference": "droppedneedle:feedback-fixes-rollback-aabbccdd",
        "entrypoint": ["tini", "--", "/entrypoint.sh"],
        "command": ["sh", "-c", "exec uvicorn main:app --workers 1"],
        "launch_command": [
            "docker",
            "compose",
            "up",
            "-d",
            "--no-build",
            "droppedneedle",
        ],
        "compose_config_sha256": "b" * 64,
    }


def _source(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    root = tmp_path / "source"
    config_dir = root / "config"
    covers = root / "cache" / "covers"
    config_dir.mkdir(parents=True)
    covers.mkdir(parents=True)
    config = config_dir / "config.json"
    config.write_text('{"schema_version":2,"library_settings":{}}', encoding="utf-8")
    environment = config_dir / ".env"
    environment.write_text("DATA_ENC_KEY=never-print-this-value\n", encoding="utf-8")
    os.chmod(environment, 0o600)
    cover = covers / "local.bin"
    cover.write_bytes(b"managed-cover")
    database = root / "cache" / "library.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE albums(id TEXT PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO albums VALUES ('local-1', 'Local album')")
    return root, database, config, environment, covers


def _capture(tmp_path: Path) -> tuple[Path, dict]:
    root, database, config, environment, covers = _source(tmp_path)
    destination = tmp_path / "closed-source-manifest"
    report = capture_complete_manifest(
        source_root=root,
        database_path=database,
        config_path=config,
        environment_path=environment,
        destination=destination,
        application_source_root=_REPOSITORY_ROOT,
        prior_application=_prior_application(),
        closed_source_confirmed=True,
    )
    return destination, report


def test_complete_manifest_round_trip_preserves_database_key_assets_and_modes(
    tmp_path: Path,
) -> None:
    manifest, report = _capture(tmp_path)
    serialized = (manifest / "manifest.json").read_text(encoding="utf-8")

    assert report["database"]["quick_check"] == "ok"
    assert report["database"]["foreign_key_failures"] == 0
    assert report["encryption_key_present"] is True
    assert "never-print-this-value" not in serialized
    assert {entry["kind"] for entry in report["files"]} == {
        "sqlite_backup",
        "config",
        "protected_environment",
        "managed_asset",
    }

    restored_root = tmp_path / "restored"
    restored = restore_complete_manifest(manifest, restored_root)
    with sqlite3.connect(restored_root / "cache" / "library.db") as connection:
        row = connection.execute("SELECT * FROM albums").fetchone()

    assert row == ("local-1", "Local album")
    assert restored["source_commit"] == report["source_identity"]["commit"]
    assert restored["prior_image_id"] == "sha256:" + "a" * 64
    assert restored["encryption_key_present"] is True
    assert (
        restored_root / "cache" / "covers" / "local.bin"
    ).read_bytes() == b"managed-cover"
    assert stat.S_IMODE((restored_root / "config" / ".env").stat().st_mode) == 0o600


def test_capture_requires_closed_source_and_protected_encryption_key(
    tmp_path: Path,
) -> None:
    root, database, config, environment, covers = _source(tmp_path)
    with pytest.raises(MaintenanceManifestError, match="every writer"):
        capture_complete_manifest(
            source_root=root,
            database_path=database,
            config_path=config,
            environment_path=environment,
            destination=tmp_path / "unsafe",
            application_source_root=_REPOSITORY_ROOT,
            prior_application=_prior_application(),
            closed_source_confirmed=False,
        )

    environment.write_text("OTHER=value\n", encoding="utf-8")
    with pytest.raises(MaintenanceManifestError, match="DATA_ENC_KEY"):
        capture_complete_manifest(
            source_root=root,
            database_path=database,
            config_path=config,
            environment_path=environment,
            destination=tmp_path / "missing-key",
            application_source_root=_REPOSITORY_ROOT,
            prior_application=_prior_application(),
            closed_source_confirmed=True,
        )


def test_validation_rejects_tampering_and_restore_refuses_nonempty_target(
    tmp_path: Path,
) -> None:
    manifest, report = _capture(tmp_path)
    asset = next(entry for entry in report["files"] if entry["kind"] == "managed_asset")
    payload = manifest / "payload" / asset["relative_path"]
    payload.write_bytes(b"tampered")

    with pytest.raises(MaintenanceManifestError, match="checksum"):
        validate_complete_manifest(manifest)

    payload.write_bytes(b"managed-cover")
    os.chmod(payload, int(asset["mode"]))
    validate_complete_manifest(manifest)
    target = tmp_path / "nonempty"
    target.mkdir()
    (target / "keep").write_text("owner data", encoding="utf-8")
    with pytest.raises(MaintenanceManifestError, match="not empty"):
        restore_complete_manifest(manifest, target)


def test_validation_rejects_manifest_path_escape(tmp_path: Path) -> None:
    manifest, report = _capture(tmp_path)
    report["files"][0]["relative_path"] = "../outside"
    (manifest / "manifest.json").write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(MaintenanceManifestError, match="escapes"):
        validate_complete_manifest(manifest)


def test_manifest_derives_assets_and_rejects_missing_database_reference(
    tmp_path: Path,
) -> None:
    root, database, config, environment, covers = _source(tmp_path)
    playlist_cover = covers / "playlists" / "mix.jpg"
    playlist_cover.parent.mkdir()
    playlist_cover.write_bytes(b"playlist-cover")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE playlists(id TEXT PRIMARY KEY, cover_image_path TEXT)"
        )
        connection.execute(
            "INSERT INTO playlists VALUES ('playlist-1', ?)",
            ("cache/covers/playlists/mix.jpg",),
        )

    destination = tmp_path / "derived"
    report = capture_complete_manifest(
        source_root=root,
        database_path=database,
        config_path=config,
        environment_path=environment,
        destination=destination,
        application_source_root=_REPOSITORY_ROOT,
        prior_application=_prior_application(),
        closed_source_confirmed=True,
    )

    assert report["managed_assets"]["missing_references"] == []
    assert report["managed_assets"]["included_file_count"] == 2
    assert (
        report["managed_assets"]["source_sha256"]
        == report["managed_assets"]["included_sha256"]
    )
    assert report["managed_assets"]["references"] == [
        {
            "kind": "playlist_cover",
            "locator": "cache/covers/playlists/mix.jpg",
            "status": "included",
        }
    ]

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE playlists SET cover_image_path = 'cache/covers/missing.jpg'"
        )
    with pytest.raises(MaintenanceManifestError, match="managed asset is missing"):
        capture_complete_manifest(
            source_root=root,
            database_path=database,
            config_path=config,
            environment_path=environment,
            destination=tmp_path / "missing-asset",
            application_source_root=_REPOSITORY_ROOT,
            prior_application=_prior_application(),
            closed_source_confirmed=True,
        )


def test_validation_pins_source_tree_and_prior_application(tmp_path: Path) -> None:
    manifest, report = _capture(tmp_path)
    current_identity = capture_source_identity(_REPOSITORY_ROOT)

    validate_complete_manifest(
        manifest,
        expected_source_identity=current_identity,
        expected_prior_application=_prior_application(),
    )
    stale_identity = {**current_identity, "worktree_sha256": "0" * 64}
    with pytest.raises(MaintenanceManifestError, match="source identity is stale"):
        validate_complete_manifest(manifest, expected_source_identity=stale_identity)
    other_prior = {**_prior_application(), "image_id": "sha256:" + "c" * 64}
    with pytest.raises(MaintenanceManifestError, match="prior application"):
        validate_complete_manifest(manifest, expected_prior_application=other_prior)
    assert report["source_identity"]["dirty"] is True


def test_in_place_rollback_requires_closed_source_and_removes_new_managed_assets(
    tmp_path: Path,
) -> None:
    manifest, _ = _capture(tmp_path)
    restored_root = tmp_path / "live-target"
    restore_complete_manifest(manifest, restored_root)
    new_asset = restored_root / "cache" / "covers" / "after-cutover.bin"
    new_asset.write_bytes(b"new-target-state")
    with sqlite3.connect(restored_root / "cache" / "library.db") as connection:
        connection.execute("UPDATE albums SET title = 'Changed target'")

    with pytest.raises(MaintenanceManifestError, match="every application writer"):
        restore_complete_manifest_in_place(
            manifest, restored_root, closed_source_confirmed=False
        )
    restored = restore_complete_manifest_in_place(
        manifest, restored_root, closed_source_confirmed=True
    )

    assert restored["prior_image_id"] == "sha256:" + "a" * 64
    assert not new_asset.exists()
    with sqlite3.connect(restored_root / "cache" / "library.db") as connection:
        assert (
            connection.execute("SELECT title FROM albums").fetchone()[0]
            == "Local album"
        )
