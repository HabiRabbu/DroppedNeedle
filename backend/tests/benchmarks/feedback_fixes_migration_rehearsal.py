"""Run the generated coherent-copy migration rehearsal and save its signed report."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

import msgspec


def _fixture_module():
    path = (
        Path(__file__).parents[1] / "infrastructure" / "test_legacy_catalog_importer.py"
    )
    spec = importlib.util.spec_from_file_location(
        "feedback_fixes_migration_fixture", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("The migration fixture module could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run(output: Path) -> dict[str, object]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="feedback-fixes-migration-") as directory:
        scratch = Path(directory)
        os.environ["ROOT_APP_DIR"] = str(scratch / "app")
        fixture = _fixture_module()
        root = scratch / "Music"
        root.mkdir()
        source = scratch / "source.db"
        target = scratch / "target.db"
        fixture._create_source(source, root)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        fixture._copy_database(source, target)
        store, importer = fixture._importer(target, root)
        legacy_before = await store.get_legacy_migration_snapshot()
        plan, dry_run = await importer.prepare("generated-rehearsal", now=100)
        applied = await importer.apply(
            "generated-rehearsal",
            expected_source_revision=plan.source_revision,
            now=101,
        )
        counts = {
            table: await store.row_count(table)
            for table in (
                "local_artists",
                "local_albums",
                "local_tracks",
                "library_identification_reviews",
                "library_migration_provenance",
                "library_reference_tombstones",
            )
        }
        report = {
            "format_version": 1,
            "fixture": "generated-coherent-copy-v1",
            "dry_run": msgspec.to_builtins(dry_run),
            "applied": msgspec.to_builtins(applied),
            "target_counts": counts,
            "target_invariants": await store.validate_migrated_catalog(),
            "source_file_unchanged": hashlib.sha256(source.read_bytes()).hexdigest()
            == source_hash,
            "working_copy_legacy_snapshot_unchanged": await store.get_legacy_migration_snapshot()
            == legacy_before,
            "elapsed_seconds": time.perf_counter() - started,
        }
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.output))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
