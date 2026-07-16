"""Apply durable local grouping contexts after target tag indexing commits."""

from __future__ import annotations

import uuid

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.identification import (
    ExistingAlbumMembership,
    GroupingApplication,
    GroupingTrack,
)
from services.native.identification_queue_service import IdentificationQueueService
from services.native.identification_revisions import album_input_revisions
from services.native.local_album_grouper import LocalAlbumGrouper, grouping_directory

_GROUPING_NAMESPACE = uuid.UUID("296d6087-edf2-4861-8c72-7eae22654aef")
ARTIST_RESOLUTION_BATCH_SIZE = 256
QUEUE_BATCH_SIZE = 256


def grouping_track_from_row(row: dict) -> GroupingTrack:
    return GroupingTrack(
        local_track_id=str(row["id"]),
        root_id=str(row["root_id"]),
        relative_path=str(row["relative_path"]),
        title=str(row["title"] or ""),
        artist_name=str(row["artist_name"] or ""),
        album_title=str(row["tag_album_title"] or ""),
        album_artist_name=str(row["tag_album_artist_name"] or ""),
        artist_sort_name=row["artist_sort"],
        album_artist_sort_name=row["album_artist_sort"],
        track_number=int(row["track_number"] or 0),
        disc_number=int(row["disc_number"] or 1),
        duration_seconds=row["duration_seconds"],
        recording_mbid=row["embedded_recording_mbid"],
        release_mbid=row["embedded_release_mbid"],
        release_group_mbid=row["embedded_release_group_mbid"],
        is_compilation=bool(row["is_compilation"]),
        tags_readable=not bool(row["metadata_incomplete"]),
        membership_locked=bool(row["membership_locked"]),
        current_album_id=str(row["local_album_id"]),
    )


def grouping_artist_candidate_id(display_name: str) -> str:
    return str(uuid.uuid5(_GROUPING_NAMESPACE, f"artist:{display_name}:group"))


def grouping_album_id(grouping_key: str) -> str:
    return str(uuid.uuid5(_GROUPING_NAMESPACE, grouping_key))


class LocalAlbumGroupingService:
    def __init__(
        self,
        store: NativeLibraryStore,
        queue: IdentificationQueueService,
        grouper: LocalAlbumGrouper | None = None,
    ) -> None:
        self._store = store
        self._queue = queue
        self._grouper = grouper or LocalAlbumGrouper()

    async def regroup_run(self, run_id: str, *, now: float) -> int:
        enqueued = 0
        while contexts := await self._store.get_pending_grouping_contexts(run_id):
            for context in contexts:
                rows = await self._store.get_grouping_context_tracks(
                    str(context["root_id"]), str(context["relative_directory"])
                )
                rows = [
                    row
                    for row in rows
                    if grouping_directory(str(row["relative_path"]))
                    == context["relative_directory"]
                ]
                memberships: dict[str, ExistingAlbumMembership] = {}
                for row in rows:
                    album_id = str(row["local_album_id"])
                    membership = memberships.setdefault(
                        album_id,
                        ExistingAlbumMembership(
                            local_album_id=album_id,
                            track_ids=[],
                            created_at=float(row["album_created_at"]),
                        ),
                    )
                    membership.track_ids.append(str(row["id"]))
                groups = self._grouper.group(
                    [grouping_track_from_row(row) for row in rows],
                    existing=list(memberships.values()),
                )
                artist_names = list(
                    dict.fromkeys(group.album_artist_name for group in groups)
                )
                artist_ids: dict[str, str] = {}
                for offset in range(0, len(artist_names), ARTIST_RESOLUTION_BATCH_SIZE):
                    names = artist_names[offset : offset + ARTIST_RESOLUTION_BATCH_SIZE]
                    candidates = [
                        (name, None, "group", grouping_artist_candidate_id(name))
                        for name in names
                    ]
                    resolved = await self._store.resolve_or_create_local_artists(
                        candidates, now=now
                    )
                    artist_ids.update(
                        {
                            name: resolved[grouping_artist_candidate_id(name)][0]
                            for name in names
                        }
                    )
                applications: list[GroupingApplication] = []
                for group in groups:
                    artist_id = artist_ids[group.album_artist_name]
                    album_id = group.retained_album_id or grouping_album_id(
                        group.grouping_key
                    )
                    applications.append(
                        GroupingApplication(
                            group=group,
                            local_album_id=album_id,
                            local_artist_id=artist_id,
                        )
                    )
                album_ids, _ = await self._store.apply_grouping_context(
                    run_id,
                    str(context["root_id"]),
                    str(context["relative_directory"]),
                    applications,
                    now=now,
                )
                refreshed_rows = await self._store.get_grouping_context_tracks(
                    str(context["root_id"]), str(context["relative_directory"])
                )
                rows_by_album: dict[str, list[dict]] = {}
                for row in refreshed_rows:
                    rows_by_album.setdefault(str(row["local_album_id"]), []).append(row)
                queue_candidates: list[tuple[str, str, str]] = []
                for album_id in album_ids:
                    album_rows = rows_by_album.get(album_id, [])
                    if not album_rows:
                        continue
                    policy = {str(row["applied_policy"]) for row in album_rows}
                    embedded = any(
                        row["embedded_release_group_mbid"]
                        or row["embedded_release_mbid"]
                        for row in album_rows
                    )
                    if policy == {"automatic"} or (
                        policy == {"local_metadata"} and embedded
                    ):
                        revisions = album_input_revisions(album_rows)
                        queue_candidates.append(
                            (
                                album_id,
                                ":".join(revisions),
                                "automatic"
                                if policy == {"automatic"}
                                else "post_processing",
                            )
                        )
                for offset in range(0, len(queue_candidates), QUEUE_BATCH_SIZE):
                    batch = queue_candidates[offset : offset + QUEUE_BATCH_SIZE]
                    dispositions = await self._queue.enqueue_albums_with_disposition(
                        batch, now=now
                    )
                    enqueued += sum(created for _, created in dispositions)
                await self._store.complete_grouping_context(
                    run_id,
                    str(context["root_id"]),
                    str(context["relative_directory"]),
                )
        return enqueued
