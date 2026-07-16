"""Previewed manual album membership and artist identity corrections."""

from __future__ import annotations

import hashlib
import time
import uuid

import msgspec

from api.v1.schemas.library_operations import (
    AutomaticGroupingPreview,
    ArtistMergeApplyRequest,
    ArtistMergePreviewRequest,
    MembershipApplyRequest,
    MembershipPreviewRequest,
    MembershipPreviewResponse,
)
from core.exceptions import StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from models.identification import ExistingAlbumMembership, GroupingApplication
from services.native.local_album_grouper import LocalAlbumGrouper, grouping_directory
from services.native.local_album_grouping_service import (
    grouping_album_id,
    grouping_artist_candidate_id,
    grouping_track_from_row,
)

PREVIEW_TTL_SECONDS = 15 * 60


def _token(kind: str, payload: object, issued_at: int) -> str:
    digest = hashlib.sha256(
        msgspec.json.encode(
            {"kind": kind, "payload": payload, "issued_at": issued_at},
            order="deterministic",
        )
    ).hexdigest()
    return f"{issued_at}.{digest}"


def _verify(token: str, kind: str, payload: object, now: float) -> None:
    try:
        issued = int(token.partition(".")[0])
    except ValueError as error:
        raise ValidationError("The catalog preview token is invalid.") from error
    if issued > now or now - issued > PREVIEW_TTL_SECONDS:
        raise StaleRevisionError(
            "The catalog preview expired. Preview the change again."
        )
    if token != _token(kind, payload, issued):
        raise StaleRevisionError("The catalog selection changed after preview.")


class CatalogCorrectionService:
    def __init__(self, store: NativeLibraryStore) -> None:
        self._store = store
        self._grouper = LocalAlbumGrouper()

    async def _automatic_reset_applications(
        self, request: MembershipPreviewRequest
    ) -> list[GroupingApplication]:
        selected = set(request.track_ids)
        contexts: dict[tuple[str, str], list[dict]] = {}
        for album_id in request.expected_album_revisions:
            album = await self._store.get_album_identification_context(album_id)
            if album is None:
                raise StaleRevisionError("Album membership changed before reset.")
            for row in album["tracks"]:
                if str(row["id"]) not in selected:
                    continue
                directory = grouping_directory(str(row["relative_path"]))
                key = (str(row["root_id"]), directory)
                if key not in contexts:
                    candidates = await self._store.get_grouping_context_tracks(*key)
                    contexts[key] = [
                        candidate
                        for candidate in candidates
                        if grouping_directory(str(candidate["relative_path"]))
                        == directory
                    ]
        applications: list[GroupingApplication] = []
        for rows in contexts.values():
            for row in rows:
                expected = request.expected_album_revisions.get(
                    str(row["local_album_id"])
                )
                if expected is None or int(row["album_row_revision"]) != expected:
                    raise StaleRevisionError(
                        "Include the current revision for every album in the reset context."
                    )
            memberships: dict[str, ExistingAlbumMembership] = {}
            grouping_tracks = []
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
                track = grouping_track_from_row(row)
                if track.local_track_id in selected:
                    track.membership_locked = False
                grouping_tracks.append(track)
            for group in self._grouper.group(
                grouping_tracks, existing=list(memberships.values())
            ):
                applications.append(
                    GroupingApplication(
                        group=group,
                        local_album_id=group.retained_album_id
                        or grouping_album_id(group.grouping_key),
                        local_artist_id=grouping_artist_candidate_id(
                            group.album_artist_name
                        ),
                    )
                )
        covered = {
            track_id
            for application in applications
            for track_id in application.group.track_ids
        }
        if not selected <= covered:
            raise ValidationError(
                "Every reset track must still exist in its stored grouping context."
            )
        return applications

    async def preview_membership(
        self,
        kind: str,
        request: MembershipPreviewRequest,
        *,
        now: float | None = None,
    ) -> MembershipPreviewResponse:
        timestamp = time.time() if now is None else now
        if kind not in {"split", "merge", "move", "reset"}:
            raise ValidationError("Unsupported catalog correction.")
        if not request.track_ids:
            raise ValidationError("Select at least one track.")
        payload = msgspec.to_builtins(request)
        contexts = []
        for album_id, revision in request.expected_album_revisions.items():
            context = await self._store.get_album_identification_context(album_id)
            if context is None or int(context["album"]["row_revision"]) != revision:
                raise StaleRevisionError("Album membership changed before preview.")
            contexts.append(context)
        selected_ids = set(request.track_ids)
        available_ids = {
            str(track["id"]) for context in contexts for track in context["tracks"]
        }
        if not selected_ids <= available_ids:
            raise ValidationError(
                "Every selected track must belong to a previewed album."
            )
        identities = {
            str(context["identity"]["release_group_mbid"])
            for context in contexts
            if context["identity"] is not None
        }
        sources = sorted(request.expected_album_revisions)
        aliases = [
            album_id for album_id in sources if album_id != request.target_album_id
        ]
        applications = (
            await self._automatic_reset_applications(request) if kind == "reset" else []
        )
        return MembershipPreviewResponse(
            preview_token=_token(kind, payload, int(timestamp)),
            source_album_ids=sources,
            target_album_id=request.target_album_id,
            track_ids=request.track_ids,
            identity_conflicts=sorted(identities) if len(identities) > 1 else [],
            aliases=aliases if kind == "merge" else [],
            automatic_groups=[
                AutomaticGroupingPreview(
                    local_album_id=application.local_album_id,
                    title=application.group.title,
                    album_artist_name=application.group.album_artist_name,
                    track_ids=application.group.track_ids,
                    reason_code=application.group.reason_code,
                )
                for application in applications
            ],
        )

    async def apply_membership(
        self,
        kind: str,
        request: MembershipApplyRequest,
        actor_user_id: str,
        *,
        now: float | None = None,
    ) -> dict:
        timestamp = time.time() if now is None else now
        payload = {
            "track_ids": request.track_ids,
            "expected_album_revisions": request.expected_album_revisions,
            "target_album_id": request.target_album_id,
            "title": request.title,
            "album_artist_name": request.album_artist_name,
        }
        _verify(request.preview_token, kind, payload, timestamp)
        if kind == "reset":
            applications = await self._automatic_reset_applications(request)
            return await self._store.apply_grouping_reset(
                track_ids=request.track_ids,
                expected_album_revisions=request.expected_album_revisions,
                applications=applications,
                actor_user_id=actor_user_id,
                idempotency_key=request.idempotency_key,
                now=timestamp,
            )
        return await self._store.apply_membership_correction(
            kind=kind,
            track_ids=request.track_ids,
            expected_album_revisions=request.expected_album_revisions,
            target_album_id=request.target_album_id,
            new_album_id=str(uuid.uuid4())
            if kind == "split" and request.target_album_id is None
            else None,
            title=request.title,
            album_artist_name=request.album_artist_name,
            identity_choice=request.identity_choice,
            actor_user_id=actor_user_id,
            idempotency_key=request.idempotency_key,
            now=timestamp,
        )

    async def preview_artist_merge(
        self, request: ArtistMergePreviewRequest, *, now: float | None = None
    ) -> MembershipPreviewResponse:
        timestamp = time.time() if now is None else now
        if request.surviving_artist_id in request.source_artist_ids:
            sources = sorted(
                set(request.source_artist_ids) - {request.surviving_artist_id}
            )
        else:
            sources = sorted(set(request.source_artist_ids))
        if not sources:
            raise ValidationError("Choose at least one duplicate artist to merge.")
        all_ids = sorted(set(sources) | {request.surviving_artist_id})
        context = await self._store.get_artist_merge_context(all_ids)
        artists = {str(row["id"]): row for row in context["artists"]}
        if set(artists) != set(all_ids):
            raise ValidationError(
                "Every selected artist must be an active local artist."
            )
        for artist_id in all_ids:
            artist = artists[artist_id]
            if artist["retired_into_artist_id"] is not None:
                raise ValidationError("A retired artist cannot be merged again.")
            if int(artist["row_revision"]) != request.expected_revisions.get(artist_id):
                raise StaleRevisionError("Artist references changed before preview.")
        provider_ids = sorted(
            {
                str(row["provider_artist_id"])
                for row in context["identities"]
                if row["provider_artist_id"]
            }
        )
        return MembershipPreviewResponse(
            preview_token=_token(
                "artist_merge", msgspec.to_builtins(request), int(timestamp)
            ),
            source_album_ids=[],
            target_album_id=request.surviving_artist_id,
            aliases=sources,
            identity_conflicts=provider_ids if len(provider_ids) > 1 else [],
            reference_counts=context["reference_counts"],
        )

    async def apply_artist_merge(
        self,
        request: ArtistMergeApplyRequest,
        actor_user_id: str,
        *,
        now: float | None = None,
    ) -> dict:
        timestamp = time.time() if now is None else now
        payload = {
            "source_artist_ids": request.source_artist_ids,
            "surviving_artist_id": request.surviving_artist_id,
            "expected_revisions": request.expected_revisions,
        }
        _verify(request.preview_token, "artist_merge", payload, timestamp)
        return await self._store.merge_local_artists(
            source_artist_ids=request.source_artist_ids,
            surviving_artist_id=request.surviving_artist_id,
            expected_revisions=request.expected_revisions,
            provider_choice=request.provider_choice,
            actor_user_id=actor_user_id,
            idempotency_key=request.idempotency_key,
            now=timestamp,
        )
