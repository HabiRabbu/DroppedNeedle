"""Bounded, priority-honest candidate recall for target identification."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable

from infrastructure.queue.priority_queue import RequestPriority
from models.identification import AlbumCandidate, GroupingTrack
from repositories.protocols.identification import IdentificationProviderProtocol
from services.native.album_evidence_engine import MAX_CANDIDATES

ALBUM_SEARCH_LIMIT = 8
RECORDING_SEARCH_LIMIT = 5
TRACK_SAMPLE_LIMIT = 4


def _consensus(values: list[str]) -> str:
    usable = [value.strip() for value in values if value.strip()]
    return Counter(usable).most_common(1)[0][0] if usable else ""


class AlbumCandidateService:
    def __init__(self, provider: IdentificationProviderProtocol) -> None:
        self._provider = provider

    async def recall(
        self,
        tracks: list[GroupingTrack],
        *,
        cached_fingerprint_release_groups: list[str] | None = None,
        explicit: bool = False,
        checkpoint: Callable[[], Awaitable[bool]] | None = None,
    ) -> list[AlbumCandidate]:
        priority = (
            RequestPriority.USER_INITIATED
            if explicit
            else RequestPriority.BACKGROUND_SYNC
        )
        ids: list[tuple[str, str]] = []
        embedded_groups = {
            track.release_group_mbid for track in tracks if track.release_group_mbid
        }
        if len(embedded_groups) == 1:
            ids.append((next(iter(embedded_groups)), "embedded"))

        album = _consensus([track.album_title for track in tracks])
        artist = _consensus([track.album_artist_name for track in tracks])
        if album and artist:
            if checkpoint is not None and not await checkpoint():
                return []
            for release_group_id in await self._provider.search_album_candidate_ids(
                f"{artist} {album}", ALBUM_SEARCH_LIMIT, priority
            ):
                ids.append((release_group_id, "album_tags"))
            if checkpoint is not None and not await checkpoint():
                return []

        if not album or not artist or len(set(identifier for identifier, _ in ids)) < 2:
            samples = sorted(
                (track for track in tracks if track.title),
                key=lambda track: (
                    track.disc_number,
                    track.track_number,
                    track.local_track_id,
                ),
            )[:TRACK_SAMPLE_LIMIT]
            for track in samples:
                if checkpoint is not None and not await checkpoint():
                    return []
                for (
                    release_group_id
                ) in await self._provider.search_recording_candidate_ids(
                    artist or track.artist_name,
                    track.title,
                    RECORDING_SEARCH_LIMIT,
                    priority,
                ):
                    ids.append((release_group_id, "recording_search"))
                if checkpoint is not None and not await checkpoint():
                    return []

        for release_group_id in cached_fingerprint_release_groups or []:
            ids.append((release_group_id, "cached_fingerprint"))

        ordered: list[str] = []
        sources: dict[str, list[str]] = {}
        for release_group_id, source in ids:
            if release_group_id not in sources:
                ordered.append(release_group_id)
                sources[release_group_id] = []
            if source not in sources[release_group_id]:
                sources[release_group_id].append(source)
        candidates: list[AlbumCandidate] = []
        for release_group_id in ordered[:MAX_CANDIDATES]:
            if checkpoint is not None and not await checkpoint():
                return []
            candidate = await self._provider.get_album_candidate(
                release_group_id, len(tracks), priority
            )
            if candidate is None:
                continue
            candidate.source_kinds = sources[release_group_id]
            candidates.append(candidate)
            if checkpoint is not None and not await checkpoint():
                return []
        return candidates
