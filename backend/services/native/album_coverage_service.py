"""Album coverage projected only from selected immutable evidence."""

from __future__ import annotations

from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.identification import AlbumCoverage
from services.native.identification_queue_service import IdentificationQueueService
from services.native.identification_revisions import album_input_revisions


class AlbumCoverageService:
    def __init__(
        self,
        store: NativeLibraryStore,
        queue: IdentificationQueueService | None = None,
    ) -> None:
        self._store = store
        self._queue = queue

    async def get_coverage(self, album_id: str) -> AlbumCoverage:
        context = await self._store.get_album_identification_context(album_id)
        if context is None:
            return AlbumCoverage(local_album_id=album_id, stale=True)
        record = await self._store.get_selected_album_evidence(album_id)
        identity = context["identity"]
        if record is None or identity is None:
            return AlbumCoverage(local_album_id=album_id)
        evidence = record.evidence
        current_inputs = album_input_revisions(context["tracks"])
        attempt_input = await self._store.get_identification_attempt_input(
            record.attempt_id
        )
        stale = attempt_input is None or current_inputs != (
            attempt_input["input_tag_revision"],
            attempt_input["input_file_revision"],
            attempt_input["input_policy_revision"],
        )
        if (
            stale
            and self._queue is not None
            and identity["decision_source"] in {"automatic", "embedded"}
            and any(
                track["applied_policy"] == "automatic" for track in context["tracks"]
            )
        ):
            await self._queue.enqueue_album(
                album_id,
                input_revision=":".join(current_inputs),
            )
        return AlbumCoverage(
            local_album_id=album_id,
            musicbrainz_release_group_id=evidence.release_group_mbid,
            identity_source=str(identity["decision_source"]),
            stale=stale,
            manual=identity["decision_source"] == "manual",
            supported=[
                track
                for track in evidence.track_evidence
                if track.classification == "supported"
            ],
            unknown=[
                track
                for track in evidence.track_evidence
                if track.classification == "unknown"
            ],
            contradictory=[
                track
                for track in evidence.track_evidence
                if track.classification == "contradictory"
            ],
            missing_expected_tracks=evidence.unmatched_expected_tracks,
            evidence_revision=record.id,
            last_evaluated_at=record.created_at,
        )
