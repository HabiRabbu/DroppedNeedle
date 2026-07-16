"""Disposable Docker/Compose rehearsal of the exact staged maintenance CLI."""

from __future__ import annotations

import argparse
import gc
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any, Sequence
from urllib.error import URLError
from urllib.request import urlopen

from cryptography.fernet import Fernet

from tests.benchmarks.feedback_fixes_maintenance_rehearsal import (
    _fixture_module,
    _write_audio_fixture,
)


_REPOSITORY_ROOT = Path(__file__).parents[3]
_PRODUCTION_CONTAINER = "droppedneedle"


def _command(
    arguments: Sequence[str],
    *,
    cwd: Path = _REPOSITORY_ROOT,
    environment: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"{result.stderr[-2000:]}"
        )
    return result.stdout


def _docker_object(target: str) -> dict[str, Any]:
    try:
        payload = json.loads(_command(["docker", "inspect", target]))
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError(f"Docker object is unreadable: {target}") from error
    if (
        not isinstance(payload, list)
        or not payload
        or not isinstance(payload[0], dict)
    ):
        raise RuntimeError(f"Docker object is missing or invalid: {target}")
    return payload[0]


def _legacy_source_image(source_image_id: str, run_id: str) -> tuple[str, str]:
    reference = f"droppedneedle-feedback-fixes-cli-{run_id}:source"
    seed_container = f"feedback-fixes-cli-{run_id}-source-image"
    _command(["docker", "create", "--name", seed_container, source_image_id])
    try:
        _command(
            [
                "docker",
                "commit",
                "--change",
                'CMD ["python", "-m", "uvicorn", "main:app", "--host", '
                '"0.0.0.0", "--port", "8688", "--workers", "1"]',
                seed_container,
                reference,
            ]
        )
        image_id = str(_docker_object(reference).get("Id") or "")
        if not image_id.startswith("sha256:"):
            raise RuntimeError("The isolated legacy source image has no immutable ID.")
        return reference, image_id
    except RuntimeError:
        subprocess.run(
            ["docker", "image", "rm", "-f", reference],
            check=False,
            capture_output=True,
            text=True,
        )
        raise
    finally:
        subprocess.run(
            ["docker", "rm", "-f", seed_container],
            check=False,
            capture_output=True,
            text=True,
        )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_health(url: str, timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:  # noqa: S310 - scratch URL
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Scratch service did not become healthy: {url}")


def _database_shape(database_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        return {
            "integrity": str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            ),
            "legacy_file_count": int(
                connection.execute("SELECT COUNT(*) FROM library_files").fetchone()[0]
            ),
            "target_catalog_present": "local_tracks" in tables,
        }
    finally:
        connection.close()


def _seed_source(scratch: Path) -> tuple[Path, Path]:
    data_root = scratch / "data"
    config_dir = data_root / "config"
    cache_dir = data_root / "cache"
    (cache_dir / "covers").mkdir(parents=True)
    config_dir.mkdir(parents=True)
    music_root = scratch / "music"
    music_root.mkdir()
    _write_audio_fixture(music_root)
    database_path = cache_dir / "library.db"
    _fixture_module()._create_source(database_path, music_root)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            "DROP TABLE auth_users;"
            "CREATE TABLE auth_users ("
            "id TEXT PRIMARY KEY, display_name TEXT NOT NULL, email TEXT UNIQUE, "
            "avatar_url TEXT, role TEXT NOT NULL DEFAULT 'user', "
            "created_at TEXT NOT NULL, last_login_at TEXT, username TEXT, "
            "username_display TEXT);"
        )
        connection.executemany(
            "INSERT INTO auth_users "
            "(id, display_name, email, role, created_at, username, username_display) "
            "VALUES (?, ?, ?, ?, '2026-07-15T00:00:00Z', ?, ?)",
            [
                ("alice", "Alice", "alice@example.test", "user", "alice", "Alice"),
                ("admin", "Admin", "admin@example.test", "admin", "admin", "Admin"),
            ],
        )
        playlist_cover = cache_dir / "covers" / "playlists" / "mix.jpg"
        playlist_cover.parent.mkdir(parents=True)
        playlist_cover.write_bytes(b"\xff\xd8\xffscratch-playlist-cover")
        connection.execute(
            "UPDATE playlists SET cover_image_path = ? WHERE id = 'playlist-1'",
            ("cache/covers/playlists/mix.jpg",),
        )
    key = Fernet.generate_key().decode()
    environment_path = config_dir / ".env"
    environment_path.write_text(f"DATA_ENC_KEY={key}\n", encoding="utf-8")
    environment_path.chmod(0o600)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connect_apps": {
                    "subsonic_enabled": True,
                    "jellyfin_enabled": True,
                },
                "library_scan_schedule": {"scan_frequency": "manual"},
                "library_settings": {
                    "library_paths": [str(music_root)],
                    "library_roots": [
                        {
                            "id": "root-1",
                            "path": str(music_root),
                            "label": "Scratch music",
                            "policy": "automatic",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (data_root / "plugins").mkdir()
    return data_root, database_path


def _compose_text(
    *,
    service_name: str,
    container_name: str,
    target_reference: str,
    scratch: Path,
    data_root: Path,
    port: int,
) -> str:
    return f"""services:
  {service_name}:
    image: ${{DROPPEDNEEDLE_IMAGE:-{target_reference}}}
    build:
      context: {_REPOSITORY_ROOT}
      dockerfile: Dockerfile
      args:
        COMMIT_TAG: feedback-fixes-cli-rehearsal
        BUILD_DATE: ''
    container_name: {container_name}
    environment:
      PUID: '{os.getuid()}'
      PGID: '{os.getgid()}'
      PORT: '8688'
      TZ: Europe/London
    ports:
      - '127.0.0.1:{port}:8688'
    volumes:
      - {data_root / 'config'}:/app/config
      - {data_root / 'cache'}:/app/cache
      - {data_root / 'plugins'}:/app/plugins
      - {scratch}:{scratch}
"""


def _stage(
    stage: str,
    *,
    state_path: Path,
    authorization: str | None = None,
    arguments: Sequence[str] = (),
) -> tuple[dict[str, Any], float]:
    command = [
        "./manage.sh",
        "--feedback-fixes",
        stage,
        "--state",
        str(state_path),
        *arguments,
    ]
    if authorization is not None:
        command.extend(["--authorization", authorization])
    started = time.perf_counter()
    output = _command(command)
    elapsed = time.perf_counter() - started
    return json.loads(output), elapsed


def run(output: Path) -> dict[str, Any]:
    started = time.perf_counter()
    production_before = _docker_object(_PRODUCTION_CONTAINER)
    if not production_before.get("State", {}).get("Running"):
        raise RuntimeError("The deployed legacy source is not running.")
    production_image_id = str(production_before["Image"])
    run_id = uuid.uuid4().hex[:10]
    project = f"feedback-fixes-cli-{run_id}"
    service = "scratch"
    container = f"feedback-fixes-cli-{run_id}"
    target_reference = f"droppedneedle-feedback-fixes-cli-{run_id}:target"
    image_prefix = f"droppedneedle-feedback-fixes-cli-{run_id}"
    transcript: list[dict[str, Any]] = []
    cleanup_references: set[str] = {target_reference}
    source_image_id = ""

    with tempfile.TemporaryDirectory(prefix="feedback-fixes-cli-") as directory:
        scratch = Path(directory)
        data_root, database_path = _seed_source(scratch)
        gc.collect()
        compose_file = scratch / "compose.yml"
        port = _free_port()
        health_url = f"http://127.0.0.1:{port}/health"
        compose_file.write_text(
            _compose_text(
                service_name=service,
                container_name=container,
                target_reference=target_reference,
                scratch=scratch,
                data_root=data_root,
                port=port,
            ),
            encoding="utf-8",
        )
        compose = ["docker", "compose", "-f", str(compose_file), "-p", project]
        state_path = scratch / "state.json"
        manifest_root = scratch / "manifest"
        try:
            source_reference, source_image_id = _legacy_source_image(
                production_image_id, run_id
            )
            cleanup_references.add(source_reference)
            setup_environment = os.environ.copy()
            setup_environment["DROPPEDNEEDLE_IMAGE"] = source_image_id
            _command(
                [*compose, "up", "-d", "--no-build", service],
                environment=setup_environment,
            )
            try:
                _wait_for_health(health_url, timeout_seconds=30)
            except RuntimeError as exc:
                logs = _command([*compose, "logs", "--no-color", service])
                raise RuntimeError(
                    f"{exc}\nScratch source logs:\n{logs[-4000:]}"
                ) from exc
            source_shape = _database_shape(database_path)
            prepare, elapsed = _stage(
                "prepare",
                state_path=state_path,
                arguments=(
                    "--repository-root",
                    str(_REPOSITORY_ROOT),
                    "--data-root",
                    str(data_root),
                    "--manifest-root",
                    str(manifest_root),
                    "--compose-file",
                    str(compose_file),
                    "--compose-project",
                    project,
                    "--service-name",
                    service,
                    "--container-name",
                    container,
                    "--target-build-reference",
                    target_reference,
                    "--image-tag-prefix",
                    image_prefix,
                    "--health-url",
                    health_url,
                ),
            )
            transcript.append({"stage": "prepare", "seconds": elapsed})
            authorization = str(prepare["authorization_challenge"])
            for stage in ("build", "stop", "capture", "migrate", "start-target"):
                summary, elapsed = _stage(
                    stage, state_path=state_path, authorization=authorization
                )
                transcript.append({"stage": stage, "seconds": elapsed})
                expected_stage = {
                    "build": "built",
                    "stop": "stopped",
                    "capture": "captured",
                    "migrate": "migrated",
                    "start-target": "target_started",
                }[stage]
                if summary["stage"] != expected_stage:
                    raise RuntimeError(
                        f"Unexpected state after {stage}: {summary['stage']}"
                    )
            _wait_for_health(health_url)
            target_shape = _database_shape(database_path)
            if not target_shape["target_catalog_present"]:
                raise RuntimeError("The exact CLI did not create the target catalog.")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            cleanup_references.update(
                {
                    state["prior_application"]["rollback_image_reference"],
                    state["target_application"]["image_reference"],
                }
            )
            summary, elapsed = _stage(
                "rollback", state_path=state_path, authorization=authorization
            )
            transcript.append({"stage": "rollback", "seconds": elapsed})
            if summary["stage"] != "rolled_back":
                raise RuntimeError("The exact CLI rollback did not complete.")
            _wait_for_health(health_url)
            rollback_shape = _database_shape(database_path)
            if rollback_shape != source_shape:
                raise RuntimeError(
                    f"Rollback shape is not the legacy source: {rollback_shape}"
                )
            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            report = {
                "schema": "feedback-fixes-cli-rehearsal-v1",
                "passed": True,
                "source_identity": final_state["source_identity"],
                "production_container_id": str(production_before["Id"]),
                "production_image_id": production_image_id,
                "scratch": {
                    "compose_project": project,
                    "container_name": container,
                    "health_url": health_url,
                    "source_image_id": source_image_id,
                    "target_image_id": final_state["target_application"]["image_id"],
                },
                "stages": transcript,
                "source_database": source_shape,
                "target_database": target_shape,
                "rollback_database": rollback_shape,
                "elapsed_seconds": time.perf_counter() - started,
            }
        finally:
            subprocess.run(
                [*compose, "down", "--remove-orphans"],
                cwd=_REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            listed_images = subprocess.run(
                ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
                check=False,
                capture_output=True,
                text=True,
            )
            cleanup_references.update(
                reference
                for reference in listed_images.stdout.splitlines()
                if reference.startswith(f"{image_prefix}:")
            )
            for reference in sorted(cleanup_references):
                subprocess.run(
                    ["docker", "image", "rm", "-f", reference],
                    check=False,
                    capture_output=True,
                    text=True,
                )

    production_after = _docker_object(_PRODUCTION_CONTAINER)
    if (
        production_after.get("Id") != production_before.get("Id")
        or production_after.get("Image") != production_before.get("Image")
        or not production_after.get("State", {}).get("Running")
    ):
        raise RuntimeError("The isolated rehearsal changed the deployed container.")
    report["production_unchanged"] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "elapsed_seconds": report["elapsed_seconds"],
                "output_sha256": sha256(args.output.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
