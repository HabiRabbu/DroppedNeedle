import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

import pytest

from maintenance import feedback_fixes


_REPOSITORY_ROOT = Path(__file__).parents[3]
_SOURCE_IMAGE = "sha256:" + "1" * 64
_TARGET_IMAGE = "sha256:" + "2" * 64
_ENTRYPOINT = ["tini", "--", "/entrypoint.sh"]
_SOURCE_COMMAND = ["sh", "-c", "exec uvicorn main:app --workers 1"]
_TARGET_COMMAND = [
    "python",
    "-m",
    "maintenance.automatic_upgrade",
    "--start-target",
]


class FakeDocker:
    def __init__(self) -> None:
        self.running = True
        self.exists = True
        self.image_id = _SOURCE_IMAGE
        self.command = list(_SOURCE_COMMAND)
        self.rollback_reference: str | None = None
        self.target_reference: str | None = None
        self.target_source_revision: str | None = None
        self.environment = ["PORT=8688", "DATA_ENC_KEY=not-recorded"]
        self.commands: list[tuple[list[str], str | None]] = []

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path | None,
        environment: dict[str, str] | None,
    ) -> str:
        arguments = list(command)
        self.commands.append(
            (arguments, environment.get("DROPPEDNEEDLE_IMAGE") if environment else None)
        )
        compose_arguments: list[str] | None = None
        if arguments[:2] == ["docker", "compose"]:
            compose_arguments = arguments[2:]
            while compose_arguments and compose_arguments[0] in {"-f", "-p"}:
                compose_arguments = compose_arguments[2:]
        if arguments[:3] == ["docker", "image", "tag"]:
            if arguments[3] == _SOURCE_IMAGE:
                self.rollback_reference = arguments[4]
            elif arguments[3] == _TARGET_IMAGE:
                self.target_reference = arguments[4]
            else:
                raise AssertionError(f"unexpected tagged image: {arguments[3]}")
            return ""
        if compose_arguments == ["stop", "droppedneedle"]:
            self.running = False
            return ""
        if compose_arguments == ["down", "--remove-orphans"]:
            self.running = False
            self.exists = False
            return ""
        if compose_arguments and compose_arguments[:2] == ["build", "--no-cache"]:
            build_arg = compose_arguments[3]
            self.target_source_revision = build_arg.split("=", 1)[1]
            return ""
        if compose_arguments and compose_arguments[0] == "up":
            self.running = True
            self.exists = True
            selected = environment.get("DROPPEDNEEDLE_IMAGE") if environment else None
            if selected == _SOURCE_IMAGE:
                self.image_id = _SOURCE_IMAGE
                self.command = list(_SOURCE_COMMAND)
            elif selected == _TARGET_IMAGE:
                self.image_id = _TARGET_IMAGE
                self.command = list(_TARGET_COMMAND)
            else:
                raise AssertionError(f"unexpected image override: {selected}")
            return ""
        if arguments[:3] == ["docker", "image", "inspect"]:
            target = arguments[3]
            if target in {_SOURCE_IMAGE, self.rollback_reference}:
                image_id = _SOURCE_IMAGE
                command_value = _SOURCE_COMMAND
            elif target in {"droppedneedle:local", self.target_reference}:
                image_id = _TARGET_IMAGE
                command_value = _TARGET_COMMAND
            else:
                raise AssertionError(f"unexpected image inspection: {target}")
            return json.dumps(
                [
                    {
                        "Id": image_id,
                        "Created": "2026-07-15T00:00:00Z",
                        "RepoDigests": [],
                        "Config": {
                            "Entrypoint": _ENTRYPOINT,
                            "Cmd": command_value,
                            "Labels": (
                                {
                                    "org.droppedneedle.source-revision": self.target_source_revision
                                }
                                if image_id == _TARGET_IMAGE
                                else {}
                            ),
                        },
                    }
                ]
            )
        if arguments == ["docker", "inspect", "droppedneedle"]:
            if not self.exists:
                raise feedback_fixes.MaintenanceStageError("container is absent")
            return json.dumps(
                [
                    {
                        "Id": "source-container-id",
                        "Image": self.image_id,
                        "Name": "/droppedneedle",
                        "State": {"Running": self.running},
                        "Config": {
                            "Image": "droppedneedle:local",
                            "Entrypoint": _ENTRYPOINT,
                            "Cmd": self.command,
                            "Env": self.environment,
                        },
                        "Mounts": [
                            {
                                "Destination": "/app/cache",
                                "Source": "/host/cache",
                                "Type": "bind",
                                "RW": True,
                            }
                        ],
                        "NetworkSettings": {"Networks": {}},
                    }
                ]
            )
        raise AssertionError(f"unexpected command: {arguments}")


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    config = root / "config"
    covers = root / "cache" / "covers"
    config.mkdir(parents=True)
    covers.mkdir(parents=True)
    (config / "config.json").write_text(
        '{"schema_version":2,"library_settings":{}}', encoding="utf-8"
    )
    environment = config / ".env"
    environment.write_text("DATA_ENC_KEY=operator-secret\n", encoding="utf-8")
    environment.chmod(0o600)
    (covers / "kept.bin").write_bytes(b"managed-artwork")
    with sqlite3.connect(root / "cache" / "library.db") as connection:
        connection.execute("CREATE TABLE albums(id TEXT PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO albums VALUES ('album-1', 'Before target')")
    return root


def test_staged_runner_pins_source_captures_migrates_starts_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = _data_root(tmp_path)
    state_path = tmp_path / "maintenance-state.json"
    manifest_root = tmp_path / "manifest"
    docker = FakeDocker()
    prepared = feedback_fixes.prepare(
        state_path=state_path,
        repository_root=_REPOSITORY_ROOT,
        data_root=data_root,
        manifest_root=manifest_root,
        runner=docker,
    )
    challenge = prepared["authorization_challenge"]

    assert prepared["stage"] == "prepared"
    assert prepared["source_identity"]["dirty"] is True
    assert prepared["prior_application"]["image_id"] == _SOURCE_IMAGE
    assert prepared["prior_application"]["command"] == _SOURCE_COMMAND
    assert "operator-secret" not in state_path.read_text(encoding="utf-8")
    with pytest.raises(feedback_fixes.MaintenanceStageError, match="does not match"):
        feedback_fixes.build(
            state_path=state_path, authorization="wrong", runner=docker
        )

    built = feedback_fixes.build(
        state_path=state_path, authorization=challenge, runner=docker
    )
    assert built["stage"] == "built"
    assert docker.running is True
    stopped = feedback_fixes.stop(
        state_path=state_path, authorization=challenge, runner=docker
    )
    assert stopped["stage"] == "stopped"
    assert docker.running is False
    assert (
        docker.rollback_reference
        == stopped["prior_application"]["rollback_image_reference"]
    )

    captured = feedback_fixes.capture(
        state_path=state_path, authorization=challenge, runner=docker
    )
    assert captured["stage"] == "captured"
    assert captured["manifest"]["file_count"] == 4

    async def fake_migration(state: dict[str, Any]) -> dict[str, Any]:
        with sqlite3.connect(state["database_path"]) as connection:
            connection.execute(
                "CREATE TABLE target_marker(id INTEGER PRIMARY KEY, ready INTEGER)"
            )
            connection.execute("INSERT INTO target_marker VALUES (1, 1)")
        return {
            "migration_id": "feedback-fixes-test",
            "source_revision": "source-revision",
            "root_revision": "root-revision",
            "prepare_seconds": 1.0,
            "apply_seconds": 2.0,
            "validation_seconds": 0.5,
            "dry_run": {},
            "applied": {},
            "startup_marker": {},
            "reported_reference_kinds": ["favorite"],
            "zero_source_reference_kinds": ["favorite"],
            "network_calls": 0,
            "tag_reads": 0,
            "fingerprints": 0,
        }

    async def fake_validate(state: dict[str, Any]) -> dict[str, Any]:
        return {"validated": True}

    monkeypatch.setattr(feedback_fixes, "_migrate_database", fake_migration)
    monkeypatch.setattr(feedback_fixes, "_validate_target_database", fake_validate)
    monkeypatch.setattr(feedback_fixes, "_wait_for_health", lambda _url: 200)
    migrated = feedback_fixes.migrate(state_path=state_path, authorization=challenge)
    assert migrated["stage"] == "migrated"
    started = feedback_fixes.start_target(
        state_path=state_path, authorization=challenge, runner=docker
    )
    assert started["stage"] == "target_started"
    assert docker.image_id == _TARGET_IMAGE

    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        connection.execute("UPDATE albums SET title = 'After target'")
    extra = data_root / "cache" / "covers" / "after-target.bin"
    extra.write_bytes(b"post-cutover-state")
    rolled_back = feedback_fixes.rollback(
        state_path=state_path, authorization=challenge, runner=docker
    )

    assert rolled_back["stage"] == "rolled_back"
    assert docker.image_id == _SOURCE_IMAGE
    assert docker.command == _SOURCE_COMMAND
    assert not extra.exists()
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        assert (
            connection.execute("SELECT title FROM albums").fetchone()[0]
            == "Before target"
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'target_marker'"
            ).fetchone()
            is None
        )


def test_prepare_refuses_active_work(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        connection.execute(
            "CREATE TABLE scan_state(id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO scan_state VALUES (1, 'scanning')")

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="workload is active"
    ):
        feedback_fixes.prepare(
            state_path=tmp_path / "state.json",
            repository_root=_REPOSITORY_ROOT,
            data_root=data_root,
            manifest_root=tmp_path / "manifest",
            runner=FakeDocker(),
        )


@pytest.mark.parametrize("unsafe_path", ["manifest", "state"])
def test_prepare_requires_recovery_files_outside_data_root(
    tmp_path: Path, unsafe_path: str
) -> None:
    data_root = _data_root(tmp_path)
    state_path = (
        data_root / "maintenance-state.json"
        if unsafe_path == "state"
        else tmp_path / "maintenance-state.json"
    )
    manifest_root = (
        data_root / "cache" / "covers" / "maintenance-manifest"
        if unsafe_path == "manifest"
        else tmp_path / "manifest"
    )

    with pytest.raises(feedback_fixes.MaintenanceStageError, match="must be outside"):
        feedback_fixes.prepare(
            state_path=state_path,
            repository_root=_REPOSITORY_ROOT,
            data_root=data_root,
            manifest_root=manifest_root,
            runner=FakeDocker(),
        )


def _prepare_and_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, FakeDocker, str]:
    data_root = _data_root(tmp_path)
    state_path = tmp_path / "maintenance-state.json"
    docker = FakeDocker()
    monkeypatch.setattr(feedback_fixes, "_wait_for_health", lambda _url: 200)
    prepared = feedback_fixes.prepare(
        state_path=state_path,
        repository_root=_REPOSITORY_ROOT,
        data_root=data_root,
        manifest_root=tmp_path / "manifest",
        runner=docker,
    )
    challenge = prepared["authorization_challenge"]
    feedback_fixes.build(state_path=state_path, authorization=challenge, runner=docker)
    return data_root, state_path, docker, challenge


def _prepare_build_stop_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, FakeDocker, str]:
    data_root, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    feedback_fixes.stop(state_path=state_path, authorization=challenge, runner=docker)
    feedback_fixes.capture(
        state_path=state_path, authorization=challenge, runner=docker
    )
    return data_root, state_path, docker, challenge


def test_stop_rechecks_download_work_started_after_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        connection.execute("CREATE TABLE download_tasks(status TEXT NOT NULL)")
        connection.execute("INSERT INTO download_tasks VALUES ('processing')")

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="started after prepare"
    ):
        feedback_fixes.stop(
            state_path=state_path, authorization=challenge, runner=docker
        )

    assert docker.running is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "built"


def test_resume_source_recovers_crash_after_stop_before_state_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    docker.running = False

    resumed = feedback_fixes.resume_source(
        state_path=state_path, authorization=challenge, runner=docker
    )

    assert resumed["stage"] == "source_resumed"
    assert docker.running is True
    assert docker.image_id == _SOURCE_IMAGE
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        assert (
            connection.execute("SELECT title FROM albums").fetchone()[0]
            == "Before target"
        )


def test_capture_failure_leaves_authorized_source_resume_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    feedback_fixes.stop(state_path=state_path, authorization=challenge, runner=docker)

    def fail_capture(**_kwargs: object) -> dict[str, Any]:
        raise feedback_fixes.MaintenanceManifestError("injected capture failure")

    monkeypatch.setattr(feedback_fixes, "capture_complete_manifest", fail_capture)
    with pytest.raises(
        feedback_fixes.MaintenanceManifestError, match="injected capture failure"
    ):
        feedback_fixes.capture(
            state_path=state_path, authorization=challenge, runner=docker
        )

    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "capturing"
    resumed = feedback_fixes.resume_source(
        state_path=state_path, authorization=challenge, runner=docker
    )
    assert resumed["stage"] == "source_resumed"
    assert docker.running is True
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        assert (
            connection.execute("SELECT title FROM albums").fetchone()[0]
            == "Before target"
        )


def test_source_drift_after_stop_still_allows_immutable_source_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _data, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    feedback_fixes.stop(state_path=state_path, authorization=challenge, runner=docker)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    changed = {**state["source_identity"], "application_revision": "changed-after-stop"}
    monkeypatch.setattr(
        feedback_fixes, "capture_source_identity", lambda _root: changed
    )

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="worktree changed after prepare"
    ):
        feedback_fixes.capture(
            state_path=state_path, authorization=challenge, runner=docker
        )

    resumed = feedback_fixes.resume_source(
        state_path=state_path, authorization=challenge, runner=docker
    )

    assert resumed["stage"] == "source_resumed"
    assert docker.running is True
    assert docker.image_id == _SOURCE_IMAGE
    assert docker.commands[-2][1] == _SOURCE_IMAGE


def test_capture_validation_failure_restores_complete_manifest_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    feedback_fixes.stop(state_path=state_path, authorization=challenge, runner=docker)
    real_validate = feedback_fixes.validate_complete_manifest
    calls = 0

    def fail_first_validation(*args: object, **kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise feedback_fixes.MaintenanceManifestError(
                "injected manifest validation failure"
            )
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(
        feedback_fixes, "validate_complete_manifest", fail_first_validation
    )
    with pytest.raises(
        feedback_fixes.MaintenanceManifestError,
        match="injected manifest validation failure",
    ):
        feedback_fixes.capture(
            state_path=state_path, authorization=challenge, runner=docker
        )
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        connection.execute("UPDATE albums SET title = 'Untrusted partial state'")

    resumed = feedback_fixes.resume_source(
        state_path=state_path, authorization=challenge, runner=docker
    )

    assert resumed["events"][-1]["restored_manifest"] is True
    with sqlite3.connect(data_root / "cache" / "library.db") as connection:
        assert connection.execute("SELECT title FROM albums").fetchone()[0] == (
            "Before target"
        )


def test_build_refuses_when_source_changes_during_image_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = _data_root(tmp_path)
    state_path = tmp_path / "state.json"
    docker = FakeDocker()
    prepared = feedback_fixes.prepare(
        state_path=state_path,
        repository_root=_REPOSITORY_ROOT,
        data_root=data_root,
        manifest_root=tmp_path / "manifest",
        runner=docker,
    )
    expected = prepared["source_identity"]
    calls = 0

    def changing_identity(_root: Path) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return expected
        return {**expected, "application_revision": "changed-during-build"}

    monkeypatch.setattr(feedback_fixes, "capture_source_identity", changing_identity)
    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="changed while.*built"
    ):
        feedback_fixes.build(
            state_path=state_path,
            authorization=prepared["authorization_challenge"],
            runner=docker,
        )

    assert docker.running is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "prepared"


def test_migrate_refuses_changed_source_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _data, state_path, _docker, challenge = _prepare_build_stop_capture(
        tmp_path, monkeypatch
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    changed = {**state["source_identity"], "application_revision": "changed"}
    monkeypatch.setattr(
        feedback_fixes, "capture_source_identity", lambda _root: changed
    )

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="before the production migration"
    ):
        feedback_fixes.migrate(state_path=state_path, authorization=challenge)

    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "captured"


def test_start_target_refuses_changed_source_and_target_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _data, state_path, docker, challenge = _prepare_build_stop_capture(
        tmp_path, monkeypatch
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stage"] = "migrated"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    changed = {**state["source_identity"], "application_revision": "changed"}
    monkeypatch.setattr(
        feedback_fixes, "capture_source_identity", lambda _root: changed
    )

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="before target admission"
    ):
        feedback_fixes.start_target(
            state_path=state_path, authorization=challenge, runner=docker
        )
    assert docker.running is False

    monkeypatch.setattr(
        feedback_fixes,
        "capture_source_identity",
        lambda _root: state["source_identity"],
    )
    docker.target_source_revision = "wrong-image-source"
    with pytest.raises(
        feedback_fixes.MaintenanceStageError,
        match="not bound to the prepared application revision",
    ):
        feedback_fixes.start_target(
            state_path=state_path, authorization=challenge, runner=docker
        )
    assert docker.running is False


def test_rollback_refuses_changed_compose_before_stopping_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _data, state_path, docker, challenge = _prepare_build_stop_capture(
        tmp_path, monkeypatch
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["prior_application"]["compose_config_sha256"] = "0" * 64
    state_path.write_text(json.dumps(state), encoding="utf-8")
    docker.running = True
    docker.image_id = _TARGET_IMAGE
    docker.command = list(_TARGET_COMMAND)

    with pytest.raises(
        feedback_fixes.MaintenanceStageError, match="Compose recipe changed"
    ):
        feedback_fixes.rollback(
            state_path=state_path, authorization=challenge, runner=docker
        )

    assert docker.running is True


def test_source_resume_rejects_runtime_shape_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _data, state_path, docker, challenge = _prepare_and_build(tmp_path, monkeypatch)
    feedback_fixes.stop(state_path=state_path, authorization=challenge, runner=docker)
    docker.environment = [*docker.environment, "UNEXPECTED=drift"]

    with pytest.raises(feedback_fixes.MaintenanceStageError, match="runtime shape"):
        feedback_fixes.resume_source(
            state_path=state_path, authorization=challenge, runner=docker
        )
