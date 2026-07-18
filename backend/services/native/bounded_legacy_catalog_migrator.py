from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import msgspec

from core.exceptions import StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.library_migration import (
    LegacyCatalogImportBundle,
    LegacyCatalogImportPlan,
    MigrationDryRunReport,
    MigrationReferenceCount,
    MigrationReview,
    MigrationTombstone,
)
from models.library_work import MigrationProvenance
from models.local_catalog import LocalArtworkAssociation
from services.native.legacy_catalog_importer import (
    REFERENCE_KINDS,
    LegacyCatalogImporter,
    _as_float,
    _fold,
    _hash,
    _stable_id,
    _valid_mbid,
)
from services.native.library_policy_resolver import LibraryPolicyResolver

BATCH_SIZE = 500
MAX_REPORTED_BLOCKERS = 100
MIN_SQLITE_ROWID = -9_223_372_036_854_775_808


@dataclass(frozen=True)
class BoundedMigrationOutcome:
    report: MigrationDryRunReport
    blocker_count: int
    invariants: dict[str, int] | None = None


class _ProgressReporter:
    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._next: dict[str, int] = {}
        self._last: dict[str, tuple[int, int]] = {}

    def start(self, phase: str, total: int) -> None:
        self._next[phase] = 0
        self.update(phase, 0, total, force=True)

    def update(
        self, phase: str, completed: int, total: int, *, force: bool = False
    ) -> None:
        interval = max(1_000, total // 20)
        next_update = self._next.get(phase, 0)
        if self._last.get(phase) == (completed, total):
            return
        if not force and completed < total and completed < next_update:
            return
        percent = 100 if total == 0 else min(100, completed * 100 // total)
        self._emit(f"[upgrade] {phase}: {completed:,}/{total:,} ({percent}%).")
        self._last[phase] = completed, total
        self._next[phase] = completed + interval


class BoundedLegacyCatalogMigrator:
    def __init__(
        self,
        store: NativeLibraryStore,
        resolver: LibraryPolicyResolver,
        *,
        emit_progress: Callable[[str], None] = print,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._store = store
        self._resolver = resolver
        self._batch_size = max(1, batch_size)
        self._progress = _ProgressReporter(emit_progress)
        self._builder = LegacyCatalogImporter(
            store,
            resolver,
            _NoCoverReader(),
            embedded_art_read_limit=0,
        )
        self._blockers: list[str] = []
        self._blocker_count = 0
        self._counts: dict[tuple[str, str | None], MigrationReferenceCount] = {
            (kind, None): MigrationReferenceCount(kind=kind) for kind in REFERENCE_KINDS
        }
        self._identified_albums = 0
        self._identified_tracks = 0
        self._local_only_albums = 0
        self._local_only_tracks = 0
        self._artists = 0

    async def migrate(
        self, migration_id: str, *, now: float | None = None
    ) -> BoundedMigrationOutcome:
        migrated_at = time.time() if now is None else now
        source_revision = await self._store.get_bounded_legacy_source_revision()
        completed_json = await self._store.get_completed_migration_report(
            migration_id,
            source_revision=source_revision,
            root_revision=self._resolver.policy_revision,
        )
        if completed_json is not None:
            report = msgspec.json.decode(completed_json, type=MigrationDryRunReport)
            if report.state != "applied":
                raise ValidationError(
                    "The completed migration does not contain an applied report."
                )
            invariants = await self._store.validate_migrated_catalog()
            if any(invariants.values()):
                raise ValidationError(
                    "The imported catalog failed its target invariants."
                )
            return BoundedMigrationOutcome(
                report=report,
                blocker_count=0,
                invariants=invariants,
            )
        totals = await self._store.get_bounded_legacy_source_counts()
        initial = self._report(
            migration_id,
            source_revision,
            state="ready",
        )
        await self._store.save_migration_dry_run(
            migration_id,
            source_revision=source_revision,
            root_revision=self._resolver.policy_revision,
            report_json=msgspec.json.encode(initial).decode(),
            created_at=migrated_at,
        )
        await self._store.prepare_bounded_legacy_migration()

        await self._migrate_roots(migration_id, source_revision, migrated_at)
        await self._migrate_identified_catalog(
            migration_id,
            source_revision,
            migrated_at,
            total=totals["library_files"],
        )
        await self._migrate_review_catalog(
            migration_id,
            source_revision,
            migrated_at,
            total=totals["manual_review_queue"],
        )
        await self._migrate_references(
            migration_id,
            source_revision,
            migrated_at,
            totals=totals,
        )
        await self._store.finish_bounded_legacy_migration()
        catalog_counts = await self._store.get_bounded_migrated_catalog_counts()
        self._identified_albums = catalog_counts["identified_albums"]
        self._identified_tracks = catalog_counts["identified_tracks"]
        self._local_only_albums = catalog_counts["local_only_albums"]
        self._local_only_tracks = catalog_counts["local_only_tracks"]
        self._artists = await self._store.get_bounded_migrated_artist_count()

        if self._blocker_count:
            return BoundedMigrationOutcome(
                report=self._report(
                    migration_id,
                    source_revision,
                    state="blocked",
                ),
                blocker_count=self._blocker_count,
            )

        final_revision = await self._store.get_bounded_legacy_source_revision()
        if final_revision != source_revision:
            raise StaleRevisionError(
                "The copied legacy database changed during its bounded migration."
            )
        invariants = await self._store.validate_migrated_catalog()
        if any(invariants.values()):
            raise ValidationError("The imported catalog failed its target invariants.")

        actual_counts = await self._store.get_migration_provenance_counts(migration_id)
        for kind in {
            "subsonic_id",
            "native_album_alias",
            "native_artist_alias",
            "artwork_reference",
        }:
            count = self._counts[(kind, None)]
            count.source = actual_counts.get(kind, 0)
            count.mapped = actual_counts.get(kind, 0)
        if any(
            actual_counts.get(kind, 0) != self._counts[(kind, None)].mapped
            for kind in REFERENCE_KINDS
        ):
            raise ValidationError(
                "The imported catalog reference counts do not match the bounded migration."
            )

        report = self._report(migration_id, source_revision, state="applied")
        await self._store.finish_migration(
            migration_id,
            source_revision=source_revision,
            report_json=msgspec.json.encode(report).decode(),
            completed_at=migrated_at,
        )
        return BoundedMigrationOutcome(
            report=report,
            blocker_count=0,
            invariants=invariants,
        )

    async def _migrate_roots(
        self, migration_id: str, source_revision: str, migrated_at: float
    ) -> None:
        rows: list[MigrationProvenance] = []
        for root in self._resolver.settings.library_roots:
            self._increment("root", mapped=True)
            rows.append(
                MigrationProvenance(
                    source_kind="root",
                    source_key=root.id,
                    target_kind="library_root",
                    target_id=root.id,
                    source_revision=_hash(msgspec.to_builtins(root)),
                    imported_at=migrated_at,
                )
            )
        await self._apply_references(
            rows,
            migration_id=migration_id,
            source_revision=source_revision,
        )

    async def _migrate_identified_catalog(
        self,
        migration_id: str,
        source_revision: str,
        migrated_at: float,
        *,
        total: int,
    ) -> None:
        phase = "Migrating catalog tracks"
        self._progress.start(phase, total)
        after_release_group: str | None = None
        after_id = ""
        current_key: str | None = None
        group_context: dict[str, Any] | None = None
        processed = 0
        while True:
            batch = await self._store.get_bounded_legacy_library_file_batch(
                after_release_group=after_release_group,
                after_id=after_id,
                limit=self._batch_size,
            )
            if not batch:
                break
            segments: list[tuple[str, list[dict[str, Any]]]] = []
            for raw in batch:
                key = str(raw.pop("__migration_release_group"))
                after_release_group = key
                after_id = str(raw.get("id") or "")
                if not segments or segments[-1][0] != key:
                    segments.append((key, []))
                segments[-1][1].append(raw)
            for key, rows in segments:
                first_segment = key != current_key
                if first_segment:
                    current_key = key
                    group_context = (
                        await self._store.get_bounded_legacy_library_group_context(key)
                        if _valid_mbid(key)
                        else None
                    )
                await self._migrate_identified_group(
                    key,
                    rows,
                    migration_id,
                    source_revision,
                    migrated_at,
                    group_context=group_context,
                    first_segment=first_segment,
                )
                processed += len(rows)
                self._progress.update(phase, processed, total)
        self._progress.update(phase, processed, total, force=True)

    async def _migrate_identified_group(
        self,
        release_group: str,
        rows: list[dict[str, Any]],
        migration_id: str,
        source_revision: str,
        migrated_at: float,
        *,
        group_context: dict[str, Any] | None,
        first_segment: bool,
    ) -> None:
        if not _valid_mbid(release_group):
            for row in rows:
                self._increment("library_file", mapped=False)
                self._add_blocker(
                    f"Library file {row.get('id')} has an invalid release-group ID."
                )
            return
        if group_context is None:
            raise ValidationError(
                "The legacy album group changed while it was being migrated."
            )
        snapshot = await self._store.get_bounded_legacy_cover_rows(release_group)
        plan = LegacyCatalogImportPlan(
            source_revision=source_revision,
            root_revision=self._resolver.policy_revision,
        )
        local_counts = self._empty_counts()
        bundle = self._builder._identified_bundle(
            release_group,
            rows,
            snapshot,
            source_revision,
            migrated_at,
            plan,
            set(),
            set(),
            {},
            {},
            {},
            defaultdict(list),
            {},
            local_counts,
            group_first=group_context["first"],
            group_is_compilation=bool(group_context["is_compilation"]),
        )
        self._merge_counts(local_counts)
        self._capture_blockers(plan.blockers)
        if bundle is None or plan.blockers:
            return
        if bundle.artwork is None and bundle.album_identity is not None:
            bundle.artwork = LocalArtworkAssociation(
                local_album_id=bundle.membership.album.id,
                cover_url=None,
                source="provider",
                source_locator=bundle.album_identity.release_group_mbid,
                updated_at=migrated_at,
            )
        bundle.membership.album.created_at = _as_float(
            group_context.get("created_at"), migrated_at
        )
        group_first = group_context["first"]
        group_root = self._resolver.resolve(str(group_first.get("file_path") or ""))
        if group_root is not None:
            bundle.membership.album.root_id = group_root.root_id
        if bundle.album_identity is not None:
            release_mbid = group_context.get("release_mbid")
            bundle.album_identity.release_mbid = (
                str(release_mbid) if release_mbid else None
            )
        await self._store.apply_legacy_catalog_bundle(
            bundle,
            migration_run_id=migration_id,
            source_revision=source_revision,
            allow_existing_artists=True,
            allow_existing_album=True,
        )
        if first_segment:
            self._identified_albums += 1
        self._identified_tracks += len(bundle.membership.tracks)
        await self._apply_references(
            self._derived_bundle_provenance(bundle, migrated_at),
            migration_id=migration_id,
            source_revision=source_revision,
        )

    async def _migrate_review_catalog(
        self,
        migration_id: str,
        source_revision: str,
        migrated_at: float,
        *,
        total: int,
    ) -> None:
        phase = "Preparing saved review tracks"
        self._progress.start(phase, total)
        after_rowid = MIN_SQLITE_ROWID
        processed = 0
        while True:
            batch = await self._store.get_bounded_legacy_rows(
                "manual_review_queue",
                after_rowid=after_rowid,
                limit=self._batch_size,
            )
            if not batch:
                break
            after_rowid = int(batch[-1]["__migration_rowid"])
            clean = [self._without_rowid(row) for row in batch]
            targets = await self._store.resolve_bounded_legacy_references(
                "review_row", clean
            )
            staged: list[tuple[int, str]] = []
            linked_reviews: list[MigrationReview] = []
            linked_provenance: list[MigrationProvenance] = []
            for raw, row, target in zip(batch, clean, targets, strict=True):
                if target is None:
                    resolved = self._resolver.resolve(str(row.get("file_path") or ""))
                    if resolved is None:
                        self._increment("review_row", mapped=False)
                        self._add_blocker(
                            f"Review row {row.get('id')} is outside every typed root."
                        )
                        continue
                    parent = Path(resolved.relative_path).parent.as_posix()
                    album = str(
                        row.get("extracted_album")
                        or Path(str(row.get("file_path") or "")).parent.name
                        or "Unknown Album"
                    )
                    staged.append(
                        (
                            int(raw["__migration_rowid"]),
                            _hash([resolved.root_id, parent, _fold(album)]),
                        )
                    )
                    continue
                review, provenance = self._linked_review(row, target[1], migrated_at)
                linked_reviews.append(review)
                linked_provenance.extend(provenance)
                self._increment("review_row", mapped=True)
                if row.get("resolution") is not None:
                    self._increment("manual_decision", mapped=True)
            if staged:
                await self._store.stage_bounded_legacy_review_groups(staged)
            if linked_reviews:
                await self._store.apply_bounded_legacy_reviews(linked_reviews)
                await self._apply_references(
                    linked_provenance,
                    migration_id=migration_id,
                    source_revision=source_revision,
                )
            processed += len(batch)
            self._progress.update(phase, processed, total)

        self._progress.update(phase, processed, total, force=True)

        pending_total = await self._store.get_bounded_legacy_pending_review_count()
        migrate_phase = "Migrating saved review tracks"
        self._progress.start(migrate_phase, pending_total)
        migrated = 0
        group_after = ""
        while True:
            keys = await self._store.get_bounded_legacy_review_group_keys(
                after_key=group_after,
                limit=self._batch_size,
            )
            if not keys:
                break
            for key in keys:
                context = await self._store.get_bounded_legacy_review_group_context(key)
                if context is None:
                    continue
                after_rowid = MIN_SQLITE_ROWID
                while True:
                    batch = await self._store.get_bounded_legacy_review_group_batch(
                        key,
                        after_rowid=after_rowid,
                        limit=self._batch_size,
                    )
                    if not batch:
                        break
                    after_rowid = int(batch[-1]["__migration_rowid"])
                    rows = [self._without_rowid(row) for row in batch]
                    await self._migrate_review_group(
                        rows,
                        migration_id,
                        source_revision,
                        migrated_at,
                        group_context=context,
                    )
                    migrated += len(rows)
                    self._progress.update(migrate_phase, migrated, pending_total)
            group_after = keys[-1]
        self._progress.update(migrate_phase, migrated, pending_total, force=True)

    async def _migrate_review_group(
        self,
        rows: list[dict[str, Any]],
        migration_id: str,
        source_revision: str,
        migrated_at: float,
        *,
        group_context: dict[str, Any],
    ) -> None:
        plan = LegacyCatalogImportPlan(
            source_revision=source_revision,
            root_revision=self._resolver.policy_revision,
        )
        local_counts = self._empty_counts()
        self._builder._add_review_rows(
            {"manual_review_queue": rows},
            source_revision,
            migrated_at,
            plan,
            set(),
            set(),
            {},
            {},
            {},
            {},
            {},
            local_counts,
            group_first=group_context["first"],
        )
        self._merge_counts(local_counts)
        self._capture_blockers(plan.blockers)
        if plan.blockers:
            return
        for bundle in plan.bundles:
            bundle.membership.album.created_at = _as_float(
                group_context.get("created_at"), migrated_at
            )
            await self._store.apply_legacy_catalog_bundle(
                bundle,
                migration_run_id=migration_id,
                source_revision=source_revision,
                allow_existing_artists=True,
                allow_existing_album=True,
            )
            self._local_only_albums += 1
            self._local_only_tracks += len(bundle.membership.tracks)
            provenance = self._derived_bundle_provenance(bundle, migrated_at)
            targets = {track.file_path: track.id for track in bundle.membership.tracks}
            for row in rows:
                if row.get("resolution") is None:
                    continue
                track_id = targets.get(str(row.get("file_path") or ""))
                if track_id is None:
                    continue
                provenance.append(
                    self._provenance(
                        "manual_decision",
                        str(row.get("id")),
                        ("local_track", track_id),
                        row,
                        migrated_at,
                    )
                )
                self._increment("manual_decision", mapped=True)
            await self._apply_references(
                provenance,
                migration_id=migration_id,
                source_revision=source_revision,
            )

    async def _migrate_references(
        self,
        migration_id: str,
        source_revision: str,
        migrated_at: float,
        *,
        totals: dict[str, int],
    ) -> None:
        sources = (
            ("user_favorites", "favorite"),
            ("play_history", "history"),
            ("playlist_tracks", "playlist_track"),
            ("album_release_pins", "album_release_pin"),
            ("compat_bookmarks", "compat_bookmark"),
            ("compat_play_queues", "compat_play_queue"),
            ("compat_play_queue_items", "compat_play_queue_item"),
            ("compat_id_map", "jellyfin_id_map"),
        )
        total = sum(totals[table] for table, _kind in sources)
        phase = "Migrating saved activity and compatibility data"
        self._progress.start(phase, total)
        await self._store.apply_reference_provenance_batch(
            [],
            migration_run_id=migration_id,
            source_revision=source_revision,
            copy_playlists=True,
        )
        processed = 0
        for table, kind in sources:
            after_rowid = MIN_SQLITE_ROWID
            while True:
                batch = await self._store.get_bounded_legacy_rows(
                    table,
                    after_rowid=after_rowid,
                    limit=self._batch_size,
                )
                if not batch:
                    break
                after_rowid = int(batch[-1]["__migration_rowid"])
                rows = [self._without_rowid(row) for row in batch]
                targets = await self._store.resolve_bounded_legacy_references(
                    kind, rows
                )
                provenance: list[MigrationProvenance] = []
                tombstones: list[MigrationTombstone] = []
                for row, target in zip(rows, targets, strict=True):
                    source_key, user_id = self._reference_key(kind, row)
                    if target is None and kind in {"playlist_track", "jellyfin_id_map"}:
                        tombstone = self._tombstone(kind, source_key, row, migrated_at)
                        tombstones.append(tombstone)
                        target = "reference_tombstone", tombstone.id
                        self._increment(
                            kind,
                            mapped=True,
                            user_id=user_id,
                            retained=kind == "jellyfin_id_map",
                            tombstoned=True,
                        )
                    else:
                        retained = target is not None and kind in {
                            "playlist_track",
                            "compat_bookmark",
                            "compat_play_queue",
                            "compat_play_queue_item",
                            "jellyfin_id_map",
                        }
                        self._increment(
                            kind,
                            mapped=target is not None,
                            user_id=user_id,
                            retained=retained,
                        )
                    if target is None:
                        self._add_blocker(
                            f"{kind} reference {source_key} cannot be resolved."
                        )
                        continue
                    provenance.append(
                        self._provenance(
                            kind,
                            source_key,
                            target,
                            row,
                            migrated_at,
                        )
                    )
                await self._apply_references(
                    provenance,
                    tombstones=tombstones,
                    migration_id=migration_id,
                    source_revision=source_revision,
                )
                processed += len(batch)
                self._progress.update(phase, processed, total)
        self._progress.update(phase, processed, total, force=True)

    def _linked_review(
        self, row: dict[str, Any], track_id: str, migrated_at: float
    ) -> tuple[MigrationReview, list[MigrationProvenance]]:
        resolution = row.get("resolution")
        review = MigrationReview(
            id=_stable_id("review", str(row.get("id"))),
            local_track_id=track_id,
            state="resolved"
            if resolution in {"accepted", "manual_id"}
            else "needs_review",
            reason_code=f"legacy_{resolution or 'unresolved'}",
            input_revision=_hash(row),
            created_at=_as_float(row.get("created_at"), migrated_at),
            updated_at=_as_float(row.get("resolved_at"), migrated_at),
            decided_at=_as_float(row.get("resolved_at")) or None,
        )
        provenance = [
            self._provenance(
                "review_row",
                str(row.get("id")),
                ("local_track", track_id),
                row,
                migrated_at,
            )
        ]
        if resolution is not None:
            provenance.append(
                self._provenance(
                    "manual_decision",
                    str(row.get("id")),
                    ("local_track", track_id),
                    row,
                    migrated_at,
                )
            )
        return review, provenance

    def _derived_bundle_provenance(
        self, bundle: LegacyCatalogImportBundle, migrated_at: float
    ) -> list[MigrationProvenance]:
        rows: list[MigrationProvenance] = []
        identity = bundle.album_identity
        if identity is not None:
            source = {"kind": "album", "id": identity.release_group_mbid}
            rows.extend(
                [
                    self._provenance(
                        "subsonic_id",
                        f"album:{identity.release_group_mbid}",
                        ("local_album", identity.local_album_id),
                        source,
                        migrated_at,
                    ),
                    self._provenance(
                        "native_album_alias",
                        identity.release_group_mbid,
                        ("local_album", identity.local_album_id),
                        source,
                        migrated_at,
                    ),
                ]
            )
        for alias in bundle.artist_aliases:
            source = {"kind": "artist", "id": alias.alias}
            rows.extend(
                [
                    self._provenance(
                        "subsonic_id",
                        f"artist:{alias.alias}",
                        ("local_artist", alias.local_artist_id),
                        source,
                        migrated_at,
                    ),
                    self._provenance(
                        "native_artist_alias",
                        alias.alias,
                        ("local_artist", alias.local_artist_id),
                        source,
                        migrated_at,
                    ),
                ]
            )
        for track in bundle.membership.tracks:
            rows.append(
                self._provenance(
                    "subsonic_id",
                    f"track:{track.id}",
                    ("local_track", track.id),
                    {"kind": "track", "id": track.id},
                    migrated_at,
                )
            )
        if bundle.artwork is not None:
            artwork = bundle.artwork
            rows.append(
                self._provenance(
                    "artwork_reference",
                    bundle.membership.album.id,
                    ("local_album", bundle.membership.album.id),
                    {
                        "cover_url": artwork.cover_url,
                        "source": artwork.source,
                        "source_locator": artwork.source_locator,
                    },
                    migrated_at,
                )
            )
        return rows

    async def _apply_references(
        self,
        rows: list[MigrationProvenance],
        *,
        migration_id: str,
        source_revision: str,
        tombstones: list[MigrationTombstone] | None = None,
    ) -> None:
        pending_tombstones = tombstones or []
        for start in range(
            0, max(len(rows), len(pending_tombstones)), self._batch_size
        ):
            await self._store.apply_reference_provenance_batch(
                rows[start : start + self._batch_size],
                migration_run_id=migration_id,
                source_revision=source_revision,
                tombstones=pending_tombstones[start : start + self._batch_size],
                copy_playlists=False,
            )

    def _reference_key(self, kind: str, row: dict[str, Any]) -> tuple[str, str | None]:
        if kind == "favorite":
            user_id = str(row.get("user_id"))
            return (
                f"{user_id}:{row.get('item_kind')}:{row.get('item_id')}",
                user_id,
            )
        if kind == "history":
            return str(row.get("id")), str(row.get("user_id"))
        if kind == "playlist_track":
            return str(row.get("id")), None
        if kind == "album_release_pin":
            return str(row.get("release_group_mbid")), None
        if kind == "compat_bookmark":
            user_id = str(row.get("user_id"))
            return f"{user_id}:{row.get('file_id')}", user_id
        if kind == "compat_play_queue":
            user_id = str(row.get("user_id"))
            return user_id, user_id
        if kind == "compat_play_queue_item":
            user_id = str(row.get("user_id"))
            return f"{user_id}:{row.get('item_index')}", user_id
        if kind == "jellyfin_id_map":
            return str(row.get("jf_id")), None
        raise ValueError(f"Unsupported bounded reference kind: {kind}")

    @staticmethod
    def _tombstone(
        kind: str, source_key: str, row: dict[str, Any], migrated_at: float
    ) -> MigrationTombstone:
        if kind == "playlist_track":
            local_source = str(row.get("source_type") or "") in {
                "local",
                "droppedneedle-local",
                "howler",
            }
            file_id = row.get("library_file_id") or (
                row.get("track_source_id") if local_source else None
            )
            return MigrationTombstone(
                id=_stable_id("playlist-tombstone", source_key),
                source_kind=kind,
                source_key=source_key,
                legacy_file_id=str(file_id) if file_id else None,
                title=str(row.get("track_name") or "Unavailable track"),
                artist_name=str(row.get("artist_name"))
                if row.get("artist_name")
                else None,
                album_name=str(row.get("album_name"))
                if row.get("album_name")
                else None,
                source_type=str(row.get("source_type")),
                created_at=migrated_at,
            )
        internal_id = str(row.get("internal_id") or "")
        item_kind = str(row.get("kind") or "")
        return MigrationTombstone(
            id=_stable_id("jellyfin-tombstone", source_key),
            source_kind=kind,
            source_key=source_key,
            legacy_file_id=internal_id if item_kind.casefold() == "track" else None,
            title=f"Unavailable Jellyfin {item_kind.casefold()}",
            source_type="jellyfin",
            created_at=migrated_at,
        )

    @staticmethod
    def _provenance(
        kind: str,
        source_key: str,
        target: tuple[str, str],
        source: object,
        migrated_at: float,
    ) -> MigrationProvenance:
        return MigrationProvenance(
            source_kind=kind,
            source_key=source_key,
            target_kind=target[0],
            target_id=target[1],
            source_revision=_hash(source),
            imported_at=migrated_at,
        )

    def _increment(
        self,
        kind: str,
        *,
        mapped: bool,
        user_id: str | None = None,
        retained: bool = False,
        tombstoned: bool = False,
    ) -> None:
        self._builder._increment(
            self._counts,
            kind,
            mapped=mapped,
            user_id=user_id,
            retained=retained,
            tombstoned=tombstoned,
        )

    def _merge_counts(
        self, source: dict[tuple[str, str | None], MigrationReferenceCount]
    ) -> None:
        for key, addition in source.items():
            target = self._counts.setdefault(
                key,
                MigrationReferenceCount(kind=addition.kind, user_id=addition.user_id),
            )
            target.source += addition.source
            target.mapped += addition.mapped
            target.duplicate += addition.duplicate
            target.unresolved += addition.unresolved
            target.retained += addition.retained
            target.tombstoned += addition.tombstoned

    @staticmethod
    def _empty_counts() -> dict[tuple[str, str | None], MigrationReferenceCount]:
        return {
            (kind, None): MigrationReferenceCount(kind=kind) for kind in REFERENCE_KINDS
        }

    def _capture_blockers(self, blockers: list[str]) -> None:
        for blocker in blockers:
            self._add_blocker(blocker)

    def _add_blocker(self, blocker: str) -> None:
        self._blocker_count += 1
        if len(self._blockers) < MAX_REPORTED_BLOCKERS:
            self._blockers.append(blocker)

    @staticmethod
    def _without_rowid(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "__migration_rowid"}

    def _report(
        self,
        migration_id: str,
        source_revision: str,
        *,
        state: str,
    ) -> MigrationDryRunReport:
        blockers = sorted(set(self._blockers))
        if self._blocker_count > len(blockers):
            blockers.append(
                f"{self._blocker_count - len(blockers)} additional blockers omitted."
            )
        return MigrationDryRunReport(
            migration_id=migration_id,
            source_revision=source_revision,
            root_revision=self._resolver.policy_revision,
            state=state,
            identified_albums=self._identified_albums,
            local_only_albums=self._local_only_albums,
            identified_tracks=self._identified_tracks,
            local_only_tracks=self._local_only_tracks,
            artists=self._artists,
            reference_counts=sorted(
                self._counts.values(),
                key=lambda item: (item.kind, item.user_id or ""),
            ),
            blockers=blockers,
            warnings=[],
            network_calls=0,
            tag_reads=0,
            fingerprints=0,
            embedded_art_reads=0,
        )


class _NoCoverReader:
    def read_cover_art(self, _path: Path) -> bytes | None:
        return None
