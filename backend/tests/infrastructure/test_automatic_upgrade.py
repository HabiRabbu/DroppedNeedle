import json
import os
import socket
import sqlite3
import subprocess
import sys
import asyncio
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import maintenance.automatic_upgrade as automatic_upgrade
from core.config import Settings
from maintenance.automatic_upgrade import (
    AutomaticUpgradeError,
    UPGRADE_ID,
    _upgrade_health_server,
    run_automatic_copy_upgrade,
    run_target_supervisor,
)
from tests.infrastructure.test_legacy_catalog_importer import _create_source


def _settings(root: Path) -> Settings:
    return Settings(
        root_app_dir=root,
        cache_dir=root / "cache",
        library_db_path=root / "cache" / "library.db",
        config_file_path=root / "config" / "config.json",
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write_unmigrated_database(path: Path, value: str = "original") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE source_value (value TEXT NOT NULL)")
        connection.execute("INSERT INTO source_value VALUES (?)", (value,))


def _mark_migrated(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS library_migration_markers "
            "(marker TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO library_migration_markers VALUES "
            "('legacy_catalog_import_complete')"
        )


def _source_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT value FROM source_value").fetchone()[0])


def test_upgrade_backs_up_and_marks_existing_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "test-version")

    def migrate(working: Path) -> dict[str, object]:
        working_database = working / "cache" / "library.db"
        with sqlite3.connect(working_database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        (working / "config" / "config.json").write_text(
            '{"name":"after"}', encoding="utf-8"
        )
        _mark_migrated(working_database)
        return {"passed": True}

    result = run_automatic_copy_upgrade(settings, runner=migrate)

    assert result == "upgraded"
    assert _source_value(settings.library_db_path) == "migrated"
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    backup = Path(state["backup_directory"])
    assert state["stage"] == "completed"
    assert _source_value(backup / "library.db") == "original"
    assert (backup / "config.json").read_text(encoding="utf-8") == '{"name":"before"}'
    assert not (backup / "working").exists()


def test_backup_captures_committed_wal_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.library_db_path.parent.mkdir(parents=True)
    with sqlite3.connect(settings.library_db_path) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE wal_value (value TEXT NOT NULL)")
        connection.execute("INSERT INTO wal_value VALUES ('committed')")
        connection.commit()
        assert Path(f"{settings.library_db_path}-wal").is_file()

        backup = automatic_upgrade.capture_upgrade_backup(settings)

        with sqlite3.connect(backup.database) as copied:
            assert (
                copied.execute("SELECT value FROM wal_value").fetchone()[0]
                == "committed"
            )


def test_failed_working_copy_keeps_database_and_settings_and_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "broken-version")
    attempts = 0

    def unexpected_restore(_settings: Settings, _backup: object) -> None:
        raise AssertionError("source restore is unnecessary before promotion")

    monkeypatch.setattr(automatic_upgrade, "restore_upgrade_backup", unexpected_restore)

    def fail(working: Path) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        with sqlite3.connect(working / "cache" / "library.db") as connection:
            connection.execute("UPDATE source_value SET value = 'partial'")
            connection.execute("CREATE TABLE partial_target (id INTEGER)")
        (working / "config" / "config.json").write_text(
            '{"name":"partial"}', encoding="utf-8"
        )
        raise RuntimeError("simulated failure")

    with pytest.raises(AutomaticUpgradeError, match="previous database"):
        run_automatic_copy_upgrade(settings, runner=fail)

    assert _source_value(settings.library_db_path) == "original"
    assert settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
    with sqlite3.connect(settings.library_db_path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'partial_target'"
            ).fetchone()
            is None
        )

    with pytest.raises(AutomaticUpgradeError, match="already tried"):
        run_automatic_copy_upgrade(settings, runner=fail)
    assert attempts == 1


def test_failed_working_migration_records_sanitized_reference_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    monkeypatch.setenv("COMMIT_TAG", "diagnostic-version")
    evidence = {
        "reason": "unresolved_references",
        "blocker_count": 3,
        "unresolved_reference_counts": {"history": 1, "playlist_track": 2},
    }

    def fail(_working: Path) -> dict[str, object]:
        raise automatic_upgrade._WorkingMigrationError("checked failure", evidence)

    with pytest.raises(AutomaticUpgradeError, match="previous database"):
        run_automatic_copy_upgrade(settings, runner=fail)

    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["failure_evidence"] == evidence
    assert "source_key" not in json.dumps(state["failure_evidence"])


def test_working_process_failure_reads_aggregate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    cache = working / "cache"
    cache.mkdir(parents=True)
    evidence = {
        "reason": "unresolved_references",
        "blocker_count": 2,
        "unresolved_reference_counts": {"jellyfin_id_map": 2},
    }
    automatic_upgrade._write_state(
        cache / automatic_upgrade._FAILURE_EVIDENCE_FILE, evidence
    )
    monkeypatch.setattr(
        automatic_upgrade.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )

    with pytest.raises(automatic_upgrade._WorkingMigrationError) as error:
        automatic_upgrade._run_working_migration(working)

    assert error.value.evidence == evidence


def test_killed_working_process_records_sanitized_exit_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    (working / "cache").mkdir(parents=True)
    monkeypatch.setattr(
        automatic_upgrade.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], -9),
    )

    with pytest.raises(automatic_upgrade._WorkingMigrationError) as error:
        automatic_upgrade._run_working_migration(working)

    assert error.value.evidence == {
        "reason": "working_process_exited",
        "returncode": -9,
    }


def test_working_process_records_sanitized_exception_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)

    async def fail() -> dict[str, object]:
        raise MemoryError("private allocation detail")

    monkeypatch.setattr(sys, "argv", ["automatic_upgrade", "--migrate-working"])
    monkeypatch.setattr(automatic_upgrade, "get_settings", lambda: settings)
    monkeypatch.setattr(automatic_upgrade, "_perform_target_migration", fail)

    assert automatic_upgrade.main() == 1
    evidence = json.loads(
        (settings.cache_dir / automatic_upgrade._FAILURE_EVIDENCE_FILE).read_text()
    )
    assert evidence == {
        "reason": "working_migration_error",
        "error_type": "MemoryError",
    }
    assert "private allocation detail" not in json.dumps(evidence)


def test_failed_fresh_install_removes_partially_created_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setenv("COMMIT_TAG", "fresh-broken")

    def fail(working: Path) -> dict[str, object]:
        _write_unmigrated_database(working / "cache" / "library.db", "partial")
        (working / "config" / "config.json").write_text("{}", encoding="utf-8")
        raise RuntimeError("simulated failure")

    with pytest.raises(AutomaticUpgradeError, match="previous database"):
        run_automatic_copy_upgrade(settings, runner=fail)

    assert not settings.library_db_path.exists()
    assert not settings.config_file_path.exists()


def test_completed_installation_skips_migration(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    _mark_migrated(settings.library_db_path)

    def unexpected(_working: Path) -> dict[str, object]:
        raise AssertionError("migration should not run")

    assert run_automatic_copy_upgrade(settings, runner=unexpected) == "ready"
    assert not (settings.cache_dir / "upgrade-backups").exists()


@pytest.mark.parametrize("damage", ["missing", "zeroed"])
def test_completed_installation_refuses_missing_or_zeroed_target_database(
    tmp_path: Path, damage: str
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=migrate) == "upgraded"
    settings.library_db_path.unlink()
    if damage == "zeroed":
        settings.library_db_path.touch()

    with pytest.raises(AutomaticUpgradeError, match="upgraded previously"):
        run_automatic_copy_upgrade(settings, runner=migrate)


def test_verified_legacy_backup_can_be_rolled_forward_again(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=migrate) == "upgraded"
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    backup = automatic_upgrade._load_upgrade_backup(settings, state["backup_directory"])
    automatic_upgrade.restore_upgrade_backup(settings, backup)

    assert run_automatic_copy_upgrade(settings, runner=migrate) == "upgraded"


def _run_real_upgrade(root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "ROOT_APP_DIR": str(root),
            "DATA_ENC_KEY": "bm90LWEtcmVhbC1rZXktZm9yLXRlc3RzLW9ubHk=",
            "COMMIT_TAG": "automatic-upgrade-test",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "maintenance.automatic_upgrade"],
        cwd=Path(__file__).parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _insert_identityless_legacy_files(
    database: Path, music: Path, *, count: int
) -> list[str]:
    ids = [f"99999999-9999-4999-8999-{index:012d}" for index in range(count)]
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO library_files "
            "(id, release_group_mbid, release_mbid, recording_mbid, disc_number, "
            "track_number, track_title, artist_name, album_artist_name, album_title, "
            "file_path, file_size_bytes, file_mtime, duration_seconds, file_format, "
            "source, is_compilation, tagged_at, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    file_id,
                    None,
                    None,
                    None,
                    1,
                    index + 1,
                    f"Local Track {index + 1}",
                    "Local Artist",
                    "Local Artist",
                    "Identityless Album",
                    str(music / "Identityless Album" / f"{index + 1:02d}.flac"),
                    1_000 + index,
                    20.0 + index,
                    180.0,
                    "flac",
                    "manual_review",
                    0,
                    21.0,
                    20.0,
                )
                for index, file_id in enumerate(ids)
            ],
        )
    return ids


def test_real_legacy_installation_upgrades_once_with_normal_startup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    music = tmp_path / "Music"
    music.mkdir(parents=True)
    database = root / "cache" / "library.db"
    database.parent.mkdir(parents=True)
    _create_source(database, music)
    config = root / "config" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"library_settings": {"library_paths": [str(music)]}}),
        encoding="utf-8",
    )

    first = _run_real_upgrade(root)
    second = _run_real_upgrade(root)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Library upgrade complete" in first.stdout
    assert "Preparing the library" not in second.stdout
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM local_tracks").fetchone()[0] == 4
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM library_migration_markers "
                "WHERE marker = 'legacy_catalog_import_complete'"
            ).fetchone()[0]
            == 1
        )
    backups = list((root / "cache" / "upgrade-backups").iterdir())
    assert len(backups) == 1
    state = json.loads(
        (root / "cache" / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["evidence"]["embedded_art_reads"] == 0


def test_real_unresolved_reference_reports_only_aggregate_failure_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    music = tmp_path / "Music"
    music.mkdir(parents=True)
    database = root / "cache" / "library.db"
    database.parent.mkdir(parents=True)
    _create_source(database, music)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO user_favorites VALUES (?, ?, ?, ?)",
            ("alice", "album", "private-missing-reference", 5),
        )
    config = root / "config" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"library_settings": {"library_paths": [str(music)]}}),
        encoding="utf-8",
    )

    result = _run_real_upgrade(root)

    assert result.returncode == 1
    state = json.loads(
        (root / "cache" / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["failure_evidence"] == {
        "reason": "unresolved_references",
        "blocker_count": 1,
        "unresolved_reference_counts": {"favorite": 1},
        "blocker_reason_counts": {"favorite_unresolved": 1},
    }
    assert "reasons: favorite_unresolved=1" in result.stdout
    serialized_evidence = json.dumps(state["failure_evidence"])
    assert "alice" not in serialized_evidence
    assert "private-missing-reference" not in serialized_evidence
    assert str(music) not in serialized_evidence
    assert not automatic_upgrade._database_has_marker(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM user_favorites WHERE item_id = ?",
            ("private-missing-reference",),
        ).fetchone() == (1,)


def test_real_upgrade_preserves_ten_identityless_legacy_library_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    music = tmp_path / "Music"
    music.mkdir(parents=True)
    database = root / "cache" / "library.db"
    database.parent.mkdir(parents=True)
    _create_source(database, music)
    legacy_ids = _insert_identityless_legacy_files(database, music, count=10)
    config = root / "config" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"library_settings": {"library_paths": [str(music)]}}),
        encoding="utf-8",
    )

    result = _run_real_upgrade(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Migrating local-only catalog tracks: 10/10 (100%)" in result.stdout
    assert "Working-copy migration checks passed" in result.stdout
    with sqlite3.connect(database) as connection:
        migrated = connection.execute(
            f"SELECT id, local_album_id FROM local_tracks WHERE id IN "
            f"({','.join('?' for _ in legacy_ids)}) ORDER BY id",
            legacy_ids,
        ).fetchall()
        reviews = connection.execute(
            "SELECT COUNT(*) FROM library_identification_reviews "
            "WHERE reason_code = 'legacy_missing_release_group_id'"
        ).fetchone()[0]
        album_identities = connection.execute(
            "SELECT COUNT(*) FROM local_album_external_identities "
            "WHERE local_album_id = ?",
            (migrated[0][1],),
        ).fetchone()[0]
    assert [row[0] for row in migrated] == sorted(legacy_ids)
    assert len({row[1] for row in migrated}) == 1
    assert reviews == 10
    assert album_identities == 0


def test_real_fresh_installation_initializes_without_user_steps(tmp_path: Path) -> None:
    root = tmp_path / "fresh"

    result = _run_real_upgrade(root)

    assert result.returncode == 0, result.stdout + result.stderr
    database = root / "cache" / "library.db"
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM local_tracks").fetchone()[0] == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM library_migration_markers "
                "WHERE marker = 'legacy_catalog_import_complete'"
            ).fetchone()[0]
            == 1
        )


def test_docker_image_runs_automatic_upgrade_before_target_application() -> None:
    dockerfile = (Path(__file__).parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert (
        'CMD ["python", "-m", "maintenance.automatic_upgrade", "--start-target"]'
        in dockerfile
    )
    assert "find /app -type f" in dockerfile
    assert "find /app/backend" not in dockerfile
    assert automatic_upgrade._target_command(8688)[-2:] == ["--workers", "1"]


def test_upgrade_health_endpoint_keeps_existing_orchestrators_waiting() -> None:
    port = _free_port()

    with _upgrade_health_server(port):
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"status": "upgrading"}
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/api/v1/library", timeout=2)

    assert error.value.code == 503


def test_copy_upgrade_promotes_only_after_the_working_database_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "copy-success")

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        (working / "config" / "config.json").write_text(
            '{"name":"after"}', encoding="utf-8"
        )
        _mark_migrated(database)
        assert _source_value(settings.library_db_path) == "original"
        assert (
            settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
        )
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=migrate) == "upgraded"
    assert _source_value(settings.library_db_path) == "migrated"
    assert settings.config_file_path.read_text(encoding="utf-8") == '{"name":"after"}'


def test_process_kill_during_copy_migration_leaves_source_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "copy-killed")

    class SimulatedProcessKill(BaseException):
        pass

    def killed(working: Path) -> dict[str, object]:
        with sqlite3.connect(working / "cache" / "library.db") as connection:
            connection.execute("UPDATE source_value SET value = 'partial'")
        (working / "config" / "config.json").write_text(
            '{"name":"partial"}', encoding="utf-8"
        )
        raise SimulatedProcessKill

    with pytest.raises(SimulatedProcessKill):
        run_automatic_copy_upgrade(settings, runner=killed)

    assert _source_value(settings.library_db_path) == "original"
    assert settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'

    def unexpected_restore(_settings: Settings, _backup: object) -> None:
        raise AssertionError("an interrupted working-copy migration changed no source")

    monkeypatch.setattr(automatic_upgrade, "restore_upgrade_backup", unexpected_restore)

    def retry(working: Path) -> dict[str, object]:
        assert _source_value(settings.library_db_path) == "original"
        assert (
            settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
        )
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        _mark_migrated(database)
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=retry) == "upgraded"
    assert _source_value(settings.library_db_path) == "migrated"


def test_process_kill_between_config_and_database_promotion_recovers_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "promotion-killed")

    class SimulatedProcessKill(BaseException):
        pass

    original_replace_database = automatic_upgrade._replace_database

    def killed_replace_database(_source: Path, _destination: Path) -> None:
        raise SimulatedProcessKill

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        _mark_migrated(database)
        (working / "config" / "config.json").write_text(
            '{"name":"after"}', encoding="utf-8"
        )
        return {"passed": True}

    monkeypatch.setattr(automatic_upgrade, "_replace_database", killed_replace_database)
    with pytest.raises(SimulatedProcessKill):
        run_automatic_copy_upgrade(settings, runner=migrate)
    assert _source_value(settings.library_db_path) == "original"
    assert settings.config_file_path.read_text(encoding="utf-8") == '{"name":"after"}'

    monkeypatch.setattr(
        automatic_upgrade, "_replace_database", original_replace_database
    )

    def retry(working: Path) -> dict[str, object]:
        assert _source_value(settings.library_db_path) == "original"
        assert (
            settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
        )
        database = working / "cache" / "library.db"
        _mark_migrated(database)
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=retry) == "upgraded"


def test_process_kill_before_pending_startup_journal_restores_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")

    class SimulatedProcessKill(BaseException):
        pass

    original_write_state = automatic_upgrade._write_state

    def killed_write_state(path: Path, payload: dict[str, object]) -> None:
        if payload.get("stage") == "promoted_pending_startup":
            raise SimulatedProcessKill
        original_write_state(path, payload)

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        (working / "config" / "config.json").write_text(
            '{"name":"after"}', encoding="utf-8"
        )
        _mark_migrated(database)
        return {"passed": True}

    monkeypatch.setattr(automatic_upgrade, "_write_state", killed_write_state)
    with pytest.raises(SimulatedProcessKill):
        run_automatic_copy_upgrade(
            settings, runner=migrate, require_target_admission=True
        )
    assert _source_value(settings.library_db_path) == "migrated"

    monkeypatch.setattr(automatic_upgrade, "_write_state", original_write_state)

    def retry(working: Path) -> dict[str, object]:
        assert _source_value(settings.library_db_path) == "original"
        assert (
            settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
        )
        database = working / "cache" / "library.db"
        _mark_migrated(database)
        return {"passed": True}

    assert run_automatic_copy_upgrade(settings, runner=retry) == "upgraded"


def test_target_exit_before_validation_restores_promoted_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)
    settings.config_file_path.parent.mkdir(parents=True)
    settings.config_file_path.write_text('{"name":"before"}', encoding="utf-8")
    monkeypatch.setenv("COMMIT_TAG", "target-start-failure")

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        (working / "config" / "config.json").write_text(
            '{"name":"after"}', encoding="utf-8"
        )
        _mark_migrated(database)
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    result = run_target_supervisor(
        settings,
        command=[sys.executable, "-c", "raise SystemExit(7)"],
        admission_timeout_seconds=1,
    )

    assert result != 0
    assert _source_value(settings.library_db_path) == "original"
    assert settings.config_file_path.read_text(encoding="utf-8") == '{"name":"before"}'
    assert not automatic_upgrade._database_has_marker(settings.library_db_path)
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "failed"


def test_target_clean_exit_before_readiness_is_still_a_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: False)

    result = run_target_supervisor(
        settings,
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        admission_timeout_seconds=1,
    )

    assert result == 1
    assert "exited before it was ready" in capsys.readouterr().out


def test_target_validation_commits_before_releasing_operational_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class FakeProcess:
        returncode = 0

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def send_signal(self, _signum: int) -> None:
            return

        def terminate(self) -> None:
            return

        def kill(self) -> None:
            return

    def start(_command: list[str], *, env: dict[str, str]) -> FakeProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, _admitted = automatic_upgrade._admission_paths(settings, token)
        automatic_upgrade._write_state(validated, {"token": token})
        return FakeProcess()

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: True)

    assert run_target_supervisor(settings, command=["target"]) == 0
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"
    assert _source_value(settings.library_db_path) == "original"


@pytest.mark.asyncio
async def test_target_lifespan_waits_for_durable_parent_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    token = "a" * 32
    monkeypatch.setenv(automatic_upgrade._ADMISSION_TOKEN_ENV, token)
    validated, admitted = automatic_upgrade._admission_paths(settings, token)

    task = asyncio.create_task(
        automatic_upgrade.await_target_startup_admission(settings)
    )
    for _ in range(20):
        if validated.is_file():
            break
        await asyncio.sleep(0.01)

    assert validated.is_file()
    assert not task.done()

    automatic_upgrade._write_state(admitted, {"token": token})
    await asyncio.wait_for(task, timeout=1)
    assert not validated.exists()
    assert not admitted.exists()


@pytest.mark.asyncio
async def test_target_startup_progress_heartbeat_advances_while_stage_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    token = "b" * 32
    monkeypatch.setenv(automatic_upgrade._ADMISSION_TOKEN_ENV, token)
    monkeypatch.setattr(
        automatic_upgrade, "_ADMISSION_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    progress_path = automatic_upgrade._admission_progress_path(settings, token)

    async with automatic_upgrade.target_startup_progress(
        settings, "catalog_validation"
    ):
        await asyncio.sleep(0.035)
        progress = automatic_upgrade._target_progress(progress_path, token)

    assert progress is not None
    assert progress["stage"] == "catalog_validation"
    assert progress["sequence"] >= 3
    assert progress["elapsed_seconds"] > 0

    async with automatic_upgrade.target_startup_progress(settings, "admission"):
        next_progress = automatic_upgrade._target_progress(progress_path, token)
    assert next_progress is not None
    assert next_progress["stage"] == "admission"
    assert next_progress["sequence"] == 1


def test_target_startup_heartbeat_extends_idle_deadline_until_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class FakeProcess:
        returncode: int | None = None

        def __init__(self) -> None:
            self.thread: threading.Thread | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            assert self.thread is not None
            self.thread.join(timeout)
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    process = FakeProcess()

    def start(_command: list[str], *, env: dict[str, str]) -> FakeProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, admitted = automatic_upgrade._admission_paths(settings, token)
        progress = automatic_upgrade._admission_progress_path(settings, token)

        def child() -> None:
            for sequence in range(1, 7):
                automatic_upgrade._write_state(
                    progress,
                    {
                        "token": token,
                        "stage": "catalog_validation",
                        "sequence": sequence,
                        "elapsed_seconds": sequence * 0.02,
                    },
                )
                time.sleep(0.02)
            automatic_upgrade._write_state(validated, {"token": token})
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not admitted.exists():
                time.sleep(0.005)
            process.returncode = 0

        process.thread = threading.Thread(target=child, daemon=True)
        process.thread.start()
        return process

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: True)

    assert (
        run_target_supervisor(
            settings,
            command=["target"],
            admission_timeout_seconds=0.04,
        )
        == 0
    )
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"


def test_target_startup_without_heartbeat_times_out_with_sanitized_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class StalledProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    monkeypatch.setattr(
        automatic_upgrade.subprocess,
        "Popen",
        lambda *_args, **_kwargs: StalledProcess(),
    )

    assert (
        run_target_supervisor(
            settings,
            command=["target"],
            admission_timeout_seconds=0.02,
        )
        == 1
    )
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["error_type"] == "TargetStartupTimeout"
    assert state["failure_evidence"]["last_stage"] == "process_start"
    assert state["failure_evidence"]["elapsed_seconds"] >= 0.02
    assert state["failure_evidence"]["returncode"] == 1
    assert _source_value(settings.library_db_path) == "original"


def test_target_startup_hard_timeout_stops_advancing_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class StalledProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    sequence = 0

    def progress(_path: Path, _token: str) -> dict[str, object]:
        nonlocal sequence
        sequence += 1
        return {
            "stage": "catalog_validation",
            "sequence": sequence,
            "elapsed_seconds": sequence * 0.01,
        }

    monkeypatch.setattr(
        automatic_upgrade.subprocess,
        "Popen",
        lambda *_args, **_kwargs: StalledProcess(),
    )
    monkeypatch.setattr(automatic_upgrade, "_target_progress", progress)
    monkeypatch.setattr(
        automatic_upgrade, "_TARGET_STARTUP_HARD_TIMEOUT_SECONDS", 0.03
    )

    assert (
        run_target_supervisor(
            settings,
            command=["target"],
            admission_timeout_seconds=1,
        )
        == 1
    )
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["error_type"] == "TargetStartupHardTimeout"
    assert state["failure_evidence"]["last_stage"] == "catalog_validation"
    assert _source_value(settings.library_db_path) == "original"


def test_post_admission_readiness_timeout_records_failure_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        _mark_migrated(database)
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class StalledProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    def start(_command: list[str], *, env: dict[str, str]) -> StalledProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, _admitted = automatic_upgrade._admission_paths(settings, token)
        automatic_upgrade._write_state(validated, {"token": token})
        return StalledProcess()

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: False)

    assert (
        run_target_supervisor(
            settings,
            command=["target"],
            admission_timeout_seconds=0.02,
        )
        == 1
    )
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"
    failure = state["target_startup_failure"]
    assert failure["error_type"] == "TargetReadinessTimeout"
    assert failure["last_stage"] == "process_start"
    assert failure["elapsed_seconds"] >= 0.02
    assert failure["returncode"] == 1
    assert _source_value(settings.library_db_path) == "migrated"

    monkeypatch.setattr(
        automatic_upgrade.subprocess,
        "Popen",
        lambda *_args, **_kwargs: StalledProcess(),
    )
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: True)
    assert run_target_supervisor(settings, command=["target"]) == 0
    recovered_state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert "target_startup_failure" not in recovered_state


def test_post_admission_clean_exit_records_failure_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        _mark_migrated(database)
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class ExitingProcess:
        returncode = 0

        def __init__(self, admitted: Path) -> None:
            self.admitted = admitted

        def poll(self) -> int | None:
            return 0 if self.admitted.exists() else None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def send_signal(self, _signum: int) -> None:
            return

        def terminate(self) -> None:
            return

        def kill(self) -> None:
            return

    def start(_command: list[str], *, env: dict[str, str]) -> ExitingProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, admitted = automatic_upgrade._admission_paths(settings, token)
        automatic_upgrade._write_state(validated, {"token": token})
        return ExitingProcess(admitted)

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(automatic_upgrade, "_target_ready", lambda _port: False)

    assert run_target_supervisor(settings, command=["target"]) == 1
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"
    assert state["target_startup_failure"]["error_type"] == (
        "TargetProcessExitedBeforeReadiness"
    )
    assert state["target_startup_failure"]["returncode"] == 0
    assert _source_value(settings.library_db_path) == "migrated"


def test_admission_write_failure_kills_unresponsive_target_and_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        _mark_migrated(working / "cache" / "library.db")
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class UnresponsiveProcess:
        returncode: int | None = None
        killed = False

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            if not self.killed:
                raise subprocess.TimeoutExpired("target", timeout)
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            return

        def terminate(self) -> None:
            return

        def kill(self) -> None:
            self.killed = True
            self.returncode = 9

    process = UnresponsiveProcess()
    original_write_state = automatic_upgrade._write_state

    def start(_command: list[str], *, env: dict[str, str]) -> UnresponsiveProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, _admitted = automatic_upgrade._admission_paths(settings, token)
        original_write_state(validated, {"token": token})
        return process

    def fail_admitted_write(path: Path, payload: dict[str, object]) -> None:
        if path.name.endswith(".admitted.json"):
            raise OSError("simulated admission write failure")
        original_write_state(path, payload)

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(automatic_upgrade, "_write_state", fail_admitted_write)

    assert run_target_supervisor(settings, command=["target"]) == 1
    assert process.killed is True
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"
    assert state["target_startup_failure"]["error_type"] == (
        "TargetAdmissionWriteError"
    )
    assert state["target_startup_failure"]["returncode"] == 9


def test_admission_commit_error_rechecks_durable_state_before_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _write_unmigrated_database(settings.library_db_path)

    def migrate(working: Path) -> dict[str, object]:
        database = working / "cache" / "library.db"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE source_value SET value = 'migrated'")
        _mark_migrated(database)
        return {"passed": True}

    run_automatic_copy_upgrade(settings, runner=migrate, require_target_admission=True)

    class StalledProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode or 0

        def send_signal(self, _signum: int) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    def start(_command: list[str], *, env: dict[str, str]) -> StalledProcess:
        token = env[automatic_upgrade._ADMISSION_TOKEN_ENV]
        validated, _admitted = automatic_upgrade._admission_paths(settings, token)
        automatic_upgrade._write_state(validated, {"token": token})
        return StalledProcess()

    original_complete = automatic_upgrade._complete_target_admission

    def complete_then_fail(current_settings: Settings) -> None:
        original_complete(current_settings)
        raise OSError("simulated post-rename fsync failure")

    monkeypatch.setattr(automatic_upgrade.subprocess, "Popen", start)
    monkeypatch.setattr(
        automatic_upgrade, "_complete_target_admission", complete_then_fail
    )

    assert run_target_supervisor(settings, command=["target"]) == 1
    state = json.loads(
        (settings.cache_dir / f"automatic-upgrade-{UPGRADE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["stage"] == "completed"
    assert state["target_startup_failure"]["error_type"] == (
        "TargetAdmissionWriteError"
    )
    assert _source_value(settings.library_db_path) == "migrated"


def test_baked_source_revision_overrides_static_compose_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = tmp_path / "revision"
    revision.write_text("backend-build-one\n", encoding="utf-8")
    monkeypatch.setattr(automatic_upgrade, "_SOURCE_REVISION_PATH", revision)
    monkeypatch.setenv("DROPPEDNEEDLE_SOURCE_REVISION", "unknown")
    monkeypatch.setenv("COMMIT_TAG", "hosting-local")

    assert automatic_upgrade._image_version() == "backend-build-one"

    revision.write_text("backend-build-two\n", encoding="utf-8")
    assert automatic_upgrade._image_version() == "backend-build-two"


def test_main_uses_the_container_port_for_upgrade_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    observed: list[int] = []

    @contextmanager
    def fake_health(port: int):
        observed.append(port)
        yield

    monkeypatch.setenv("PORT", "9876")
    monkeypatch.setattr(sys, "argv", ["automatic_upgrade"])
    monkeypatch.setattr(automatic_upgrade, "get_settings", lambda: settings)
    monkeypatch.setattr(automatic_upgrade, "_upgrade_health_server", fake_health)
    monkeypatch.setattr(
        automatic_upgrade,
        "run_automatic_copy_upgrade",
        lambda _settings, **_kwargs: "upgraded",
    )

    assert automatic_upgrade.main() == 0
    assert observed == [9876]


def test_main_removes_default_config_when_fresh_upgrade_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)

    def create_default_settings() -> Settings:
        settings.config_file_path.parent.mkdir(parents=True, exist_ok=True)
        settings.config_file_path.write_text('{"generated":true}', encoding="utf-8")
        return settings

    @contextmanager
    def fake_health(_port: int):
        yield

    def fail(_settings: Settings, **_kwargs: object) -> str:
        raise AutomaticUpgradeError("simulated failure")

    monkeypatch.setenv("ROOT_APP_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["automatic_upgrade"])
    monkeypatch.setattr(automatic_upgrade, "get_settings", create_default_settings)
    monkeypatch.setattr(automatic_upgrade, "_upgrade_health_server", fake_health)
    monkeypatch.setattr(automatic_upgrade, "run_automatic_copy_upgrade", fail)

    assert automatic_upgrade.main() == 1
    assert not settings.config_file_path.exists()
