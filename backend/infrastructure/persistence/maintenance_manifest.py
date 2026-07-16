"""Complete closed-source recovery manifests for offline catalog replacement."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Iterable


MANIFEST_FORMAT_VERSION = 2
MANIFEST_FILENAME = "manifest.json"
PAYLOAD_DIRECTORY = "payload"
_MANAGED_ASSET_ROOTS = (Path("cache/covers"), Path("cache/avatars"))


class MaintenanceManifestError(RuntimeError):
    """The recovery unit is incomplete, stale, unsafe, or corrupt."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_items(items: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(items):
        digest.update(name.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _git_output(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MaintenanceManifestError(
            "The application source revision could not be derived from Git."
        ) from exc
    return result.stdout


def capture_source_identity(source_tree: Path) -> dict[str, Any]:
    """Derive an exact identity for tracked and untracked application source files."""

    root = source_tree.resolve(strict=True)
    commit = _git_output(root, "rev-parse", "HEAD").decode().strip()
    status = _git_output(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    diff = _git_output(root, "diff", "--binary", "HEAD", "--")
    listed = _git_output(root, "ls-files", "-co", "--exclude-standard", "-z").split(
        b"\0"
    )
    tree_items: list[tuple[str, str]] = []
    for encoded in sorted(item for item in listed if item):
        relative = encoded.decode("utf-8", errors="surrogateescape")
        path = root / relative
        if path.is_symlink():
            value = "symlink:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
        elif path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            value = f"file:{mode:o}:{_sha256(path)}"
        else:
            value = "missing"
        tree_items.append((relative, value))
    worktree_sha256 = _digest_items(tree_items)
    return {
        "commit": commit,
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "worktree_sha256": worktree_sha256,
        "application_revision": f"{commit}+worktree:{worktree_sha256[:16]}",
        "file_count": len(tree_items),
    }


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise MaintenanceManifestError(
            "Every manifest source must be inside the application data root."
        )
    if resolved.is_symlink() or path.is_symlink():
        raise MaintenanceManifestError("Manifest sources cannot be symbolic links.")
    return PurePosixPath(*resolved.relative_to(root).parts).as_posix()


def _safe_relative(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise MaintenanceManifestError("A manifest path is missing.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise MaintenanceManifestError("A manifest path escapes its recovery root.")
    return Path(*relative.parts)


def _contains_encryption_key(path: Path) -> bool:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "DATA_ENC_KEY" and value.strip():
            return True
    return False


def _database_metadata(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        foreign_key_failures = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
        schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        schema_digest = hashlib.sha256(
            json.dumps(schema_rows, separators=(",", ":")).encode()
        ).hexdigest()
        table_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        )
    return {
        "quick_check": quick_check,
        "foreign_key_failures": foreign_key_failures,
        "schema_version": schema_version,
        "schema_sha256": schema_digest,
        "table_count": table_count,
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if exists is None:
        return set()
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _reference_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if "://" in text or text.startswith(("data:", "/api/")):
        return None
    candidate = Path(text)
    if candidate.is_absolute() and candidate.parts[:2] == ("/", "app"):
        candidate = root.joinpath(*candidate.parts[2:])
    elif not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return candidate.resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def derive_managed_assets(source_root: Path, database_path: Path) -> dict[str, Any]:
    """Inventory every managed cache root and explicit database-backed asset path."""

    root = source_root.resolve(strict=True)
    sources: dict[str, Path] = {}
    managed_roots: list[str] = []
    references: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for relative in _MANAGED_ASSET_ROOTS:
        path = root / relative
        if path.exists():
            sources[relative.as_posix()] = path
            managed_roots.append(relative.as_posix())

    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for table in ("playlists", "library_playlists"):
            if "cover_image_path" not in _table_columns(connection, table):
                continue
            rows = connection.execute(
                f'SELECT cover_image_path FROM "{table}" '
                "WHERE cover_image_path IS NOT NULL AND cover_image_path != ''"
            ).fetchall()
            for row in rows:
                raw = str(row["cover_image_path"])
                path = _reference_path(root, raw)
                if path is None:
                    references.append(
                        {
                            "kind": "playlist_cover",
                            "locator": raw,
                            "status": "derivable",
                        }
                    )
                elif path.is_file():
                    relative = _relative(root, path)
                    sources[relative] = path
                    references.append(
                        {"kind": "playlist_cover", "locator": raw, "status": "included"}
                    )
                else:
                    missing.append({"kind": "playlist_cover", "locator": raw})

        artwork_columns = _table_columns(connection, "local_album_artwork")
        if {"source", "source_locator"}.issubset(artwork_columns):
            rows = connection.execute(
                "SELECT source, source_locator FROM local_album_artwork "
                "WHERE source_locator IS NOT NULL AND source_locator != ''"
            ).fetchall()
            for row in rows:
                source = str(row["source"] or "")
                locator = str(row["source_locator"])
                if source in {"embedded", "provider"}:
                    status = "external_or_audio_backed"
                else:
                    path = _reference_path(root, locator)
                    status = (
                        "included"
                        if path is not None and path.is_file()
                        else "covered_by_managed_cache"
                    )
                    if path is not None and path.is_file():
                        sources[_relative(root, path)] = path
                references.append(
                    {
                        "kind": f"local_artwork_{source}",
                        "locator": locator,
                        "status": status,
                    }
                )

    if missing:
        raise MaintenanceManifestError(
            "A database-referenced non-derivable managed asset is missing."
        )
    expanded = _expand_assets(root, sources.values())
    return {
        "sources": expanded,
        "managed_roots": sorted(managed_roots),
        "references": sorted(
            references, key=lambda item: (item["kind"], item["locator"])
        ),
        "missing_references": [],
        "source_file_count": len(expanded),
        "source_bytes": sum(path.stat().st_size for path in expanded),
        "source_sha256": _digest_items(
            (_relative(root, path), _sha256(path)) for path in expanded
        ),
    }


def _expand_assets(root: Path, sources: Iterable[Path]) -> list[Path]:
    files: dict[str, Path] = {}
    for source in sources:
        resolved = source.resolve(strict=True)
        _relative(root, resolved)
        candidates = (
            sorted(path for path in resolved.rglob("*") if path.is_file())
            if resolved.is_dir()
            else [resolved]
        )
        for candidate in candidates:
            relative = _relative(root, candidate)
            files[relative] = candidate
    return [files[key] for key in sorted(files)]


def _copy_entry(
    *, source: Path, destination: Path, root: Path, kind: str
) -> dict[str, Any]:
    relative = _relative(root, source)
    target = destination / PAYLOAD_DIRECTORY / _safe_relative(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=False)
    return {
        "kind": kind,
        "relative_path": relative,
        "size_bytes": target.stat().st_size,
        "mode": stat.S_IMODE(source.stat().st_mode),
        "sha256": _sha256(target),
    }


def _validate_prior_application(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaintenanceManifestError("Prior application metadata is missing.")
    image_id = value.get("image_id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise MaintenanceManifestError(
            "The prior application image ID is not immutable."
        )
    if not isinstance(value.get("entrypoint"), list) or not isinstance(
        value.get("command"), list
    ):
        raise MaintenanceManifestError(
            "The prior launch entrypoint or command is missing."
        )
    rollback_reference = value.get("rollback_image_reference")
    if not isinstance(rollback_reference, str) or not rollback_reference:
        raise MaintenanceManifestError("The rollback image reference is missing.")
    launch_command = value.get("launch_command")
    if not isinstance(launch_command, list) or not launch_command:
        raise MaintenanceManifestError(
            "The executable rollback launch command is missing."
        )
    return value


def capture_complete_manifest(
    *,
    source_root: Path,
    database_path: Path,
    config_path: Path,
    environment_path: Path,
    destination: Path,
    application_source_root: Path,
    prior_application: dict[str, Any],
    closed_source_confirmed: bool,
) -> dict[str, Any]:
    """Capture one complete recovery unit after the caller has stopped all writers."""

    if not closed_source_confirmed:
        raise MaintenanceManifestError(
            "Refusing capture until the application and every writer are stopped."
        )
    root = source_root.resolve(strict=True)
    database = database_path.resolve(strict=True)
    config = config_path.resolve(strict=True)
    environment = environment_path.resolve(strict=True)
    for required in (database, config, environment):
        _relative(root, required)
    if not _contains_encryption_key(environment):
        raise MaintenanceManifestError(
            "The protected environment file does not contain DATA_ENC_KEY."
        )
    if destination.exists():
        raise MaintenanceManifestError("The manifest destination already exists.")

    source_identity = capture_source_identity(application_source_root)
    prior = _validate_prior_application(prior_application)
    asset_inventory = derive_managed_assets(root, database)
    started = perf_counter()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    try:
        database_relative = _relative(root, database)
        backup = staging / PAYLOAD_DIRECTORY / _safe_relative(database_relative)
        backup.parent.mkdir(parents=True, exist_ok=True)
        with (
            sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source,
            sqlite3.connect(backup) as target,
        ):
            source.backup(target, pages=256)
        os.chmod(backup, stat.S_IMODE(database.stat().st_mode))
        entries = [
            {
                "kind": "sqlite_backup",
                "relative_path": database_relative,
                "size_bytes": backup.stat().st_size,
                "mode": stat.S_IMODE(database.stat().st_mode),
                "sha256": _sha256(backup),
            },
            _copy_entry(source=config, destination=staging, root=root, kind="config"),
            _copy_entry(
                source=environment,
                destination=staging,
                root=root,
                kind="protected_environment",
            ),
        ]
        protected = {
            database_relative,
            _relative(root, config),
            _relative(root, environment),
        }
        for asset in asset_inventory.pop("sources"):
            if _relative(root, asset) not in protected:
                entries.append(
                    _copy_entry(
                        source=asset,
                        destination=staging,
                        root=root,
                        kind="managed_asset",
                    )
                )

        try:
            config_payload = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MaintenanceManifestError("config.json is not valid JSON.") from exc
        if not isinstance(config_payload, dict):
            raise MaintenanceManifestError("config.json must contain an object.")
        database_metadata = _database_metadata(backup)
        if (
            database_metadata["quick_check"] != "ok"
            or database_metadata["foreign_key_failures"] != 0
        ):
            raise MaintenanceManifestError(
                "The coherent SQLite backup failed integrity validation."
            )
        included_assets = [
            entry for entry in entries if entry["kind"] == "managed_asset"
        ]
        asset_inventory["included_file_count"] = len(included_assets)
        asset_inventory["included_bytes"] = sum(
            int(entry["size_bytes"]) for entry in included_assets
        )
        asset_inventory["included_sha256"] = _digest_items(
            (str(entry["relative_path"]), str(entry["sha256"]))
            for entry in included_assets
        )
        if (
            asset_inventory["source_file_count"]
            != asset_inventory["included_file_count"]
            or asset_inventory["source_bytes"] != asset_inventory["included_bytes"]
            or asset_inventory["source_sha256"] != asset_inventory["included_sha256"]
        ):
            raise MaintenanceManifestError("The managed asset inventory is incomplete.")
        report = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_identity": source_identity,
            "source_commit": source_identity["commit"],
            "application_revision": source_identity["application_revision"],
            "prior_application": prior,
            "config_schema_version": config_payload.get("schema_version", 1),
            "database": database_metadata,
            "database_relative_path": database_relative,
            "protected_environment_relative_path": _relative(root, environment),
            "encryption_key_present": True,
            "closed_source_confirmed": True,
            "managed_assets": asset_inventory,
            "files": sorted(entries, key=lambda entry: entry["relative_path"]),
            "capture_seconds": perf_counter() - started,
        }
        (staging / MANIFEST_FILENAME).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    validate_complete_manifest(destination)
    return report


def validate_complete_manifest(
    manifest_root: Path,
    *,
    expected_source_identity: dict[str, Any] | None = None,
    expected_prior_application: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate paths, hashes, modes, identities, assets, and the coherent database."""

    try:
        report = json.loads(
            (manifest_root / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaintenanceManifestError("The manifest metadata is unreadable.") from exc
    if (
        not isinstance(report, dict)
        or report.get("format_version") != MANIFEST_FORMAT_VERSION
    ):
        raise MaintenanceManifestError("The manifest format version is unsupported.")
    source_identity = report.get("source_identity")
    if not isinstance(source_identity, dict) or not all(
        isinstance(source_identity.get(key), expected_type)
        for key, expected_type in (
            ("commit", str),
            ("worktree_sha256", str),
            ("diff_sha256", str),
            ("application_revision", str),
        )
    ):
        raise MaintenanceManifestError("The source identity is incomplete.")
    if (
        expected_source_identity is not None
        and source_identity != expected_source_identity
    ):
        raise MaintenanceManifestError("The manifest source identity is stale.")
    prior = _validate_prior_application(report.get("prior_application"))
    if expected_prior_application is not None and prior != expected_prior_application:
        raise MaintenanceManifestError("The manifest prior application does not match.")
    files = report.get("files")
    if not isinstance(files, list) or not files:
        raise MaintenanceManifestError("The manifest contains no recovery files.")
    kinds: set[str] = set()
    seen: set[Path] = set()
    asset_entries: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise MaintenanceManifestError("A manifest file entry is invalid.")
        relative = _safe_relative(entry.get("relative_path"))
        if relative in seen:
            raise MaintenanceManifestError("A manifest path is duplicated.")
        seen.add(relative)
        kind = entry.get("kind")
        if not isinstance(kind, str):
            raise MaintenanceManifestError("A manifest file kind is invalid.")
        kinds.add(kind)
        if kind == "managed_asset":
            asset_entries.append(entry)
        payload = manifest_root / PAYLOAD_DIRECTORY / relative
        if not payload.is_file() or payload.is_symlink():
            raise MaintenanceManifestError("A manifest payload file is missing.")
        if payload.stat().st_size != entry.get("size_bytes") or _sha256(
            payload
        ) != entry.get("sha256"):
            raise MaintenanceManifestError(
                "A manifest payload checksum does not match."
            )
        if stat.S_IMODE(payload.stat().st_mode) != entry.get("mode"):
            raise MaintenanceManifestError("A manifest payload mode does not match.")
    required = {"sqlite_backup", "config", "protected_environment"}
    if not required.issubset(kinds):
        raise MaintenanceManifestError(
            "The manifest is missing a required recovery kind."
        )
    inventory = report.get("managed_assets")
    if not isinstance(inventory, dict) or inventory.get("missing_references") != []:
        raise MaintenanceManifestError(
            "The managed asset reconciliation is incomplete."
        )
    if (
        inventory.get("included_file_count") != len(asset_entries)
        or inventory.get("included_bytes")
        != sum(int(entry["size_bytes"]) for entry in asset_entries)
        or inventory.get("included_sha256")
        != _digest_items(
            (str(entry["relative_path"]), str(entry["sha256"]))
            for entry in asset_entries
        )
    ):
        raise MaintenanceManifestError("The managed asset inventory is stale.")
    environment = (
        manifest_root
        / PAYLOAD_DIRECTORY
        / _safe_relative(report.get("protected_environment_relative_path"))
    )
    if not _contains_encryption_key(environment):
        raise MaintenanceManifestError(
            "The protected manifest environment is missing DATA_ENC_KEY."
        )
    database = (
        manifest_root
        / PAYLOAD_DIRECTORY
        / _safe_relative(report.get("database_relative_path"))
    )
    metadata = _database_metadata(database)
    if metadata != report.get("database"):
        raise MaintenanceManifestError("The manifest database metadata is stale.")
    return report


def restore_complete_manifest(manifest_root: Path, target_root: Path) -> dict[str, Any]:
    """Restore a validated recovery unit into an empty isolated root."""

    report = validate_complete_manifest(manifest_root)
    if target_root.exists() and any(target_root.iterdir()):
        raise MaintenanceManifestError("The restore target is not empty.")
    started = perf_counter()
    target_root.mkdir(parents=True, exist_ok=True)
    restored_bytes = _restore_entries(report, manifest_root, target_root)
    restored = _restore_report(report, target_root, restored_bytes, started)
    validate_restored_manifest(report, target_root)
    return restored


def restore_complete_manifest_in_place(
    manifest_root: Path,
    target_root: Path,
    *,
    closed_source_confirmed: bool,
) -> dict[str, Any]:
    """Restore the exact recovery unit over a stopped target during rollback."""

    if not closed_source_confirmed:
        raise MaintenanceManifestError(
            "Refusing rollback restore until every application writer is stopped."
        )
    report = validate_complete_manifest(manifest_root)
    started = perf_counter()
    target_root.mkdir(parents=True, exist_ok=True)
    inventory = report["managed_assets"]
    for relative in inventory.get("managed_roots", []):
        managed_root = target_root / _safe_relative(relative)
        if managed_root.exists():
            shutil.rmtree(managed_root)
    database = target_root / _safe_relative(report["database_relative_path"])
    for suffix in ("-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)
    restored_bytes = _restore_entries(report, manifest_root, target_root)
    restored = _restore_report(report, target_root, restored_bytes, started)
    validate_restored_manifest(report, target_root)
    return restored


def _restore_entries(
    report: dict[str, Any], manifest_root: Path, target_root: Path
) -> int:
    restored_bytes = 0
    for entry in report["files"]:
        relative = _safe_relative(entry["relative_path"])
        source = manifest_root / PAYLOAD_DIRECTORY / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.feedback-fixes-restore")
        shutil.copy2(source, temporary, follow_symlinks=False)
        os.chmod(temporary, int(entry["mode"]))
        os.replace(temporary, target)
        restored_bytes += int(entry["size_bytes"])
    return restored_bytes


def _restore_report(
    report: dict[str, Any], target_root: Path, restored_bytes: int, started: float
) -> dict[str, Any]:
    return {
        "format_version": report["format_version"],
        "source_commit": report["source_commit"],
        "application_revision": report["application_revision"],
        "prior_image_id": report["prior_application"]["image_id"],
        "file_count": len(report["files"]),
        "restored_bytes": restored_bytes,
        "restore_seconds": perf_counter() - started,
        "encryption_key_present": _contains_encryption_key(
            target_root / _safe_relative(report["protected_environment_relative_path"])
        ),
    }


def validate_restored_manifest(report: dict[str, Any], target_root: Path) -> None:
    """Refuse a restored source whose files no longer match the manifest."""

    for entry in report["files"]:
        target = target_root / _safe_relative(entry["relative_path"])
        if not target.is_file() or target.is_symlink():
            raise MaintenanceManifestError("A restored manifest file is missing.")
        if (
            target.stat().st_size != entry["size_bytes"]
            or _sha256(target) != entry["sha256"]
        ):
            raise MaintenanceManifestError(
                "A restored manifest checksum does not match."
            )
        if stat.S_IMODE(target.stat().st_mode) != entry["mode"]:
            raise MaintenanceManifestError("A restored manifest mode does not match.")
    database = target_root / _safe_relative(report["database_relative_path"])
    if _database_metadata(database) != report["database"]:
        raise MaintenanceManifestError("The restored database metadata does not match.")
