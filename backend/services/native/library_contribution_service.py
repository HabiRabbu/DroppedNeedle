from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import logging
import re
import secrets
import time
import uuid
from typing import Any, Literal, TypeVar
from urllib.parse import urlencode, urlsplit

import msgspec

from core.exceptions import (
    ContributionDataError,
    ContributionDuplicateCheckRequiredError,
    ContributionExactDuplicateError,
    ContributionProviderExpiredError,
    ContributionResultMismatchError,
    ContributionStateError,
    ResourceNotFoundError,
    ValidationError,
)
from infrastructure.persistence.native_library_store import NativeLibraryStore
from infrastructure.cache.cache_keys import library_identification_prefixes
from infrastructure.cache.memory_cache import CacheInterface
from models.library_contribution import (
    ContributionRecord,
    ContributionSourceSelection,
    ContributionValidationIssue,
    DiscogsRelease,
    DiscogsReleaseCandidate,
    DiscogsSourceView,
    DuplicateCandidate,
    DuplicateCheckResult,
    LocalReleaseSnapshot,
    ReleaseDraft,
    ReleaseMediumDraft,
    ReleaseMediumSnapshot,
    ReleaseTextField,
    ReleaseTrackDraft,
    ReleaseTrackSnapshot,
    SourceReference,
    TrackAlignment,
    MusicBrainzDuplicateFacts,
    MusicBrainzSeed,
    MusicBrainzSeedField,
    MusicBrainzVerifiedRelease,
)
from infrastructure.queue.priority_queue import RequestPriority
from repositories.protocols.discogs import DiscogsRepositoryProtocol
from repositories.protocols.musicbrainz import MusicBrainzRepositoryProtocol
from models.identification import (
    AlbumCandidate,
    CandidateTrack,
    GroupingTrack,
    IdentificationAttempt,
    IdentificationDecision,
    IdentificationEvidenceRecord,
)
from services.native.album_evidence_engine import MATCHER_VERSION, AlbumEvidenceEngine
from services.native.identification_revisions import album_input_revisions

_Document = TypeVar("_Document")
_MAX_TEXT_LENGTH = 1_000
_DISCOGS_DISPLAY_SECONDS = 6 * 60 * 60
_DISCOGS_HOSTS = {"discogs.com", "www.discogs.com"}
_DISCOGS_RELEASE_PATH = re.compile(r"^/release/(?P<id>[1-9]\d*)(?:-[^/]*)?/?$")
_MUSICBRAINZ_RELEASE_EDITOR = "https://musicbrainz.org/release/add"
_MUSICBRAINZ_DISCOGS_RELEASE_LINK_TYPE = "76"
_CALLBACK_PATH = "/api/v1/library/contributions/musicbrainz/callback"
_CALLBACK_TOKEN_SECONDS = 30 * 60
_CALLBACK_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_MUSICBRAINZ_RELEASE_PATH = re.compile(r"^/release/(?P<mbid>[0-9a-fA-F-]{36})/?$")

logger = logging.getLogger(__name__)


class LibraryContributionService:
    def __init__(
        self,
        store: NativeLibraryStore,
        discogs_repository: DiscogsRepositoryProtocol | None = None,
        musicbrainz_repository: MusicBrainzRepositoryProtocol | None = None,
        cache: CacheInterface | None = None,
    ) -> None:
        self._store = store
        self._discogs = discogs_repository
        self._musicbrainz = musicbrainz_repository
        self._cache = cache
        self._evidence = AlbumEvidenceEngine()

    async def create(self, album_id: str, actor_user_id: str) -> ContributionRecord:
        snapshot = await self._build_local_snapshot(album_id)
        if snapshot.musicbrainz_release_id:
            raise ContributionStateError(
                "This local album already has an exact MusicBrainz release."
            )
        draft = self._draft_from_snapshot(snapshot)
        row = await self._store.create_or_get_library_contribution(
            local_album_id=album_id,
            actor_user_id=actor_user_id,
            album_row_revision=snapshot.album_row_revision,
            input_revision=snapshot.input_revision,
            local_snapshot_json=self._encode(snapshot),
            resolved_draft_json=self._encode(draft),
            source_selection_json=self._encode(ContributionSourceSelection()),
            now=time.time(),
        )
        return await self._record(row)

    async def get(self, contribution_id: str) -> ContributionRecord:
        row = await self._store.get_library_contribution(contribution_id)
        if row is None:
            raise ResourceNotFoundError("Library contribution not found.")
        if self._row_is_stale(row) and row["state"] not in {
            "linked",
            "cancelled",
            "stale",
        }:
            row = await self._store.mark_library_contribution_stale(
                contribution_id=contribution_id,
                expected_row_revision=int(row["row_revision"]),
                now=time.time(),
            )
        return await self._record(row)

    async def active_for_album(self, album_id: str) -> ContributionRecord | None:
        row = await self._store.get_active_album_contribution(album_id)
        if row is None:
            return None
        if self._row_is_stale(row):
            row = await self._store.mark_library_contribution_stale(
                contribution_id=str(row["id"]),
                expected_row_revision=int(row["row_revision"]),
                now=time.time(),
            )
        return await self._record(row)

    async def update(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        draft: ReleaseDraft,
        actor_user_id: str,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.state == "stale":
            raise ContributionStateError(
                "The local album changed. Rebuild this contribution before editing."
            )
        discogs_release = await self._current_discogs_release(current)
        normalized = self._normalize_draft(
            draft,
            current.local_snapshot,
            current.source_selection,
            discogs_release,
        )
        issues = self._validate(normalized, current.local_snapshot)
        state = "ready" if not issues else "draft"
        row = await self._store.update_library_contribution_draft(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            resolved_draft_json=self._encode(normalized),
            state=state,
            now=time.time(),
        )
        return await self._record(row)

    async def search_discogs(
        self, contribution_id: str, query: str | None
    ) -> list[DiscogsReleaseCandidate]:
        current = await self.get(contribution_id)
        if current.state in {"stale", "linked", "cancelled"}:
            raise ContributionStateError(
                "This contribution cannot search for another source."
            )
        repository = self._require_discogs()
        search_query = " ".join((query or "").split())
        if not search_query:
            search_query = (
                f"{current.local_snapshot.album_artist_name} "
                f"{current.local_snapshot.title}"
            ).strip()
        if len(search_query) < 2:
            raise ValidationError("Enter a release title, artist, barcode, URL, or ID.")
        if len(search_query) > 200:
            raise ValidationError("The Discogs search is too long.")
        return await repository.search_releases(
            search_query,
            priority=RequestPriority.USER_INITIATED,
            limit=8,
        )

    async def select_discogs(
        self,
        contribution_id: str,
        *,
        release_id_or_url: str,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.row_revision != expected_row_revision:
            raise ContributionStateError(
                "The contribution changed before the source was selected."
            )
        release_id = self.parse_discogs_release_id(release_id_or_url)
        release = await self._require_discogs().get_release(
            release_id, priority=RequestPriority.USER_INITIATED
        )
        if release is None:
            raise ResourceNotFoundError("That Discogs release could not be found.")
        alignments = self._align_tracks(current.local_snapshot, release)
        sources = [
            SourceReference(
                provider="discogs",
                entity_type="release",
                external_id=release.release_id,
                canonical_url=release.canonical_release_url,
                fetched_at=release.source_fetched_at,
            )
        ]
        if release.master_id and release.canonical_master_url:
            sources.append(
                SourceReference(
                    provider="discogs",
                    entity_type="master",
                    external_id=release.master_id,
                    canonical_url=release.canonical_master_url,
                    fetched_at=release.source_fetched_at,
                )
            )
        selection = ContributionSourceSelection(
            sources=sources,
            alignments=alignments,
        )
        expires_at = release.source_fetched_at + _DISCOGS_DISPLAY_SECONDS
        row = await self._store.select_discogs_source_for_contribution(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            release_id=release.release_id,
            canonical_url=release.canonical_release_url,
            source_selection_json=self._encode(selection),
            provider_snapshot_expires_at=expires_at,
            verified_at=release.source_fetched_at,
            now=time.time(),
        )
        return await self._record(row, discogs_release=release)

    async def remove_discogs(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.row_revision != expected_row_revision:
            raise ContributionStateError(
                "The contribution changed before the source was removed."
            )
        draft = self._without_discogs_values(current.draft, current.local_snapshot)
        issues = self._validate(draft, current.local_snapshot)
        state = "ready" if not issues else "draft"
        row = await self._store.remove_discogs_source_from_contribution(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            source_selection_json=self._encode(ContributionSourceSelection()),
            resolved_draft_json=self._encode(draft),
            state=state,
            now=time.time(),
        )
        return await self._record(row)

    async def check_duplicates(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
        different_edition_confirmed: bool,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.row_revision != expected_row_revision:
            raise ContributionStateError(
                "The contribution changed before the duplicate check started."
            )
        if current.state not in {"ready", "needs_review"} or current.validation:
            raise ContributionStateError(
                "Complete the contribution draft before checking MusicBrainz."
            )
        if current.discogs_source and current.discogs_source.expired:
            raise ContributionProviderExpiredError(
                "Refresh the Discogs source before checking MusicBrainz."
            )
        repository = self._require_musicbrainz()
        candidates: dict[str, DuplicateCandidate] = {}
        discogs_release = (
            current.discogs_source.release if current.discogs_source else None
        )
        exact_release_ids: list[str] = []
        group_ids: list[str] = []
        if discogs_release is not None:
            exact_resolution = await repository.resolve_url(
                discogs_release.canonical_release_url,
                includes=("release-rels",),
                priority=RequestPriority.USER_INITIATED,
            )
            exact_release_ids = exact_resolution.release_mbids
            if discogs_release.canonical_master_url:
                group_resolution = await repository.resolve_url(
                    discogs_release.canonical_master_url,
                    includes=("release-group-rels",),
                    priority=RequestPriority.USER_INITIATED,
                )
                group_ids = group_resolution.release_group_mbids
        for release_mbid in exact_release_ids:
            verified = await repository.get_release_for_verification(
                release_mbid, priority=RequestPriority.USER_INITIATED
            )
            candidates[f"release:{release_mbid}"] = self._duplicate_candidate(
                current,
                verified,
                release_mbid=release_mbid,
                evidence_kind="exact_discogs_url",
                exact=True,
            )
        for group_mbid in group_ids:
            candidates[f"group:{group_mbid}"] = DuplicateCandidate(
                release_mbid=None,
                release_group_mbid=group_mbid,
                title=current.draft.title.value or "",
                artist_name=current.draft.artist_credit.value or "",
                evidence_kind="release_group",
                exact=False,
                differences=[
                    "This Discogs master is linked to an existing release group."
                ],
            )
        facts = MusicBrainzDuplicateFacts(
            title=current.draft.title.value or "",
            artist_name=current.draft.artist_credit.value or "",
            barcode=current.draft.barcode.value,
            country=current.draft.country.value,
            date=current.draft.release_date.value,
        )
        similar = await repository.search_duplicate_releases(
            facts,
            priority=RequestPriority.USER_INITIATED,
            limit=8,
        )
        for verified in similar:
            key = f"release:{verified.release_mbid}"
            if key in candidates:
                continue
            evidence_kind = (
                "barcode"
                if facts.barcode
                and verified.barcode
                and facts.barcode == verified.barcode
                else "similar"
            )
            candidates[key] = self._duplicate_candidate(
                current,
                verified,
                release_mbid=verified.release_mbid,
                evidence_kind=evidence_kind,
                exact=False,
            )
        ordered = sorted(
            candidates.values(),
            key=lambda candidate: (
                {
                    "exact_discogs_url": 0,
                    "release_group": 1,
                    "barcode": 2,
                    "similar": 3,
                }[candidate.evidence_kind],
                candidate.release_mbid or candidate.release_group_mbid or "",
            ),
        )
        serious_similar = any(
            candidate.evidence_kind in {"barcode", "similar"} for candidate in ordered
        )
        ambiguous_group = len(group_ids) > 1
        state = (
            "needs_review"
            if exact_release_ids
            or ambiguous_group
            or (serious_similar and not different_edition_confirmed)
            else "ready"
        )
        now = time.time()
        result = DuplicateCheckResult(
            checked_at=now,
            input_revision=current.input_revision,
            candidates=ordered,
            different_edition_confirmed=(
                different_edition_confirmed and not exact_release_ids
            ),
        )
        row = await self._store.record_library_contribution_duplicate_result(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            duplicate_result_json=self._encode(result),
            duplicate_input_revision=current.input_revision,
            state=state,
            now=now,
        )
        return await self._record(row, discogs_release=discogs_release)

    async def attach_existing(
        self,
        contribution_id: str,
        *,
        release_mbid: str,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.row_revision != expected_row_revision:
            raise ContributionStateError(
                "The contribution changed before the release could be attached."
            )
        duplicate = current.duplicate_result
        if duplicate is None:
            raise ContributionDuplicateCheckRequiredError(
                "Run the MusicBrainz duplicate check first."
            )
        exact = [candidate for candidate in duplicate.candidates if candidate.exact]
        if len(exact) > 1:
            raise ContributionResultMismatchError(
                "The Discogs relationship points to more than one MusicBrainz release."
            )
        selected = next(
            (
                candidate
                for candidate in duplicate.candidates
                if candidate.release_mbid == release_mbid
            ),
            None,
        )
        if selected is None:
            raise ContributionResultMismatchError(
                "That release is not in the current duplicate-check result."
            )
        verified = await self._require_musicbrainz().get_release_for_verification(
            release_mbid,
            priority=RequestPriority.USER_INITIATED,
            bypass_cache=True,
        )
        if verified is None:
            raise ResourceNotFoundError(
                "The MusicBrainz release could not be verified."
            )
        decision, context = await self.build_attachment_evidence(current, verified)
        if decision.outcome != "identified":
            raise ContributionResultMismatchError(
                "The MusicBrainz release does not safely match the current draft."
            )
        now = time.time()
        tag_revision, file_revision, policy_revision = album_input_revisions(
            context["tracks"]
        )
        attempt_id = str(uuid.uuid4())
        evidence = [
            IdentificationEvidenceRecord(
                id=str(uuid.uuid4()),
                attempt_id=attempt_id,
                candidate_key=(
                    f"{candidate.release_group_mbid}:{candidate.release_mbid or ''}"
                ),
                evidence=candidate,
                created_at=now,
            )
            for candidate in decision.candidates
        ]
        attempt = IdentificationAttempt(
            id=attempt_id,
            local_album_id=current.local_album_id,
            trigger="contribution_submission",
            requested_by_user_id=actor_user_id,
            input_tag_revision=tag_revision,
            input_file_revision=file_revision,
            input_policy_revision=policy_revision,
            matcher_version=MATCHER_VERSION,
            state="identified",
            terminal_reason_code=decision.reason_code,
            selected_candidate_key=decision.selected_candidate_key,
            candidate_count=len(decision.candidates),
            started_at=now,
            completed_at=now,
        )
        row = await self._store.attach_existing_release_for_contribution(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            release_mbid=verified.release_mbid,
            release_group_mbid=verified.release_group_mbid,
            artist_mbid=verified.artist_mbid,
            matcher_version=MATCHER_VERSION,
            attempt=attempt,
            evidence=evidence,
            now=now,
        )
        if await self._purge_provider_data_row(row, now=now):
            row = await self._store.get_library_contribution(contribution_id) or row
        await self._invalidate_catalog_cache()
        return await self._record(row)

    async def create_musicbrainz_seed(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
        public_base_url: str,
    ) -> MusicBrainzSeed:
        parsed_base = urlsplit(public_base_url)
        if (
            parsed_base.scheme not in {"http", "https"}
            or not parsed_base.hostname
            or parsed_base.username is not None
            or parsed_base.password is not None
        ):
            raise ValidationError("The public DroppedNeedle URL is not valid.")
        current = await self.get(contribution_id)
        if current.row_revision != expected_row_revision:
            raise ContributionStateError(
                "The contribution changed before the editor could be opened."
            )
        duplicate = current.duplicate_result
        if duplicate is None:
            raise ContributionDuplicateCheckRequiredError(
                "Run the MusicBrainz duplicate check first."
            )
        if any(candidate.exact for candidate in duplicate.candidates):
            raise ContributionExactDuplicateError(
                "This Discogs release already has a MusicBrainz release."
            )
        serious = any(
            candidate.evidence_kind in {"barcode", "similar"}
            for candidate in duplicate.candidates
        )
        if serious and not duplicate.different_edition_confirmed:
            raise ContributionDuplicateCheckRequiredError(
                "Confirm that the MusicBrainz candidates are different editions."
            )
        discogs_release = await self._current_discogs_release(current)
        if current.discogs_source and discogs_release is None:
            raise ContributionProviderExpiredError(
                "Refresh the Discogs source before opening MusicBrainz."
            )
        if discogs_release is not None:
            fresh_resolution = await self._require_musicbrainz().resolve_url(
                discogs_release.canonical_release_url,
                includes=("release-rels",),
                priority=RequestPriority.USER_INITIATED,
                bypass_cache=True,
            )
            if fresh_resolution.release_mbids:
                raise ContributionExactDuplicateError(
                    "This Discogs release is now linked to MusicBrainz. Run the duplicate check again."
                )
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        expires_at = now + _CALLBACK_TOKEN_SECONDS
        callback_url = f"{public_base_url.rstrip('/')}{_CALLBACK_PATH}?{urlencode({'token': token})}"
        fields = await self._musicbrainz_seed_fields(
            current,
            discogs_release=discogs_release,
            redirect_uri=callback_url,
        )
        safe_snapshot = {
            "schema_version": 1,
            "input_revision": current.input_revision,
            "fields": [
                {"name": field.name, "value": field.value}
                for field in fields
                if field.name != "redirect_uri"
            ],
        }
        snapshot_json = msgspec.json.encode(safe_snapshot).decode()
        seed_hash = hashlib.sha256(
            msgspec.json.encode(msgspec.to_builtins(fields))
        ).hexdigest()
        row = await self._store.prepare_library_contribution_seed(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            token_hash=token_hash,
            token_expires_at=expires_at,
            seed_snapshot_json=snapshot_json,
            seed_hash=seed_hash,
            now=now,
        )
        return MusicBrainzSeed(
            action_url=_MUSICBRAINZ_RELEASE_EDITOR,
            fields=fields,
            contribution_revision=int(row["row_revision"]),
            expires_at=expires_at,
        )

    async def consume_musicbrainz_callback(
        self, token: str | None, release_mbid: str | None
    ) -> str:
        if token is None or not _CALLBACK_TOKEN.fullmatch(token):
            raise ValidationError("The MusicBrainz callback token is invalid.")
        if release_mbid is None or len(release_mbid) > 64:
            raise ValidationError("The MusicBrainz release MBID is invalid.")
        normalized_mbid = self.parse_musicbrainz_release_id(release_mbid or "")
        (
            contribution_id,
            _job_id,
        ) = await self._store.consume_library_contribution_callback_token(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            release_mbid=normalized_mbid,
            now=time.time(),
        )
        return contribution_id

    async def record_manual_result(
        self,
        contribution_id: str,
        *,
        release_id_or_url: str,
        expected_row_revision: int,
        actor_user_id: str,
        replace_existing_result: bool = False,
    ) -> ContributionRecord:
        release_mbid = self.parse_musicbrainz_release_id(release_id_or_url)
        row = await self._store.record_library_contribution_manual_result(
            contribution_id=contribution_id,
            release_mbid=release_mbid,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            replace_existing_result=replace_existing_result,
            now=time.time(),
        )
        return await self._record(row)

    async def retry_verification(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        row = await self._store.requeue_library_contribution_verification(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            now=time.time(),
        )
        return await self._record(row)

    async def build_attachment_evidence(
        self,
        contribution: ContributionRecord,
        verified: MusicBrainzVerifiedRelease,
    ) -> tuple[IdentificationDecision, dict[str, Any]]:
        context = await self._store.get_album_identification_context(
            contribution.local_album_id
        )
        if context is None:
            raise ResourceNotFoundError("Library album not found.")
        recording_mbids = {
            str(track["id"]): (
                track.get("recording_mbid") or track.get("embedded_recording_mbid")
            )
            for track in context["tracks"]
        }
        return (
            self._attachment_evidence(
                contribution,
                verified,
                recording_mbids=recording_mbids,
            ),
            context,
        )

    async def invalidate_catalog_cache(self) -> None:
        await self._invalidate_catalog_cache()

    @staticmethod
    def parse_musicbrainz_release_id(value: str) -> str:
        candidate = value.strip()
        if "://" in candidate:
            try:
                parsed = urlsplit(candidate)
                port = parsed.port
            except ValueError as error:
                raise ValidationError(
                    "Enter a MusicBrainz release MBID or release URL."
                ) from error
            if (
                parsed.scheme != "https"
                or parsed.hostname != "musicbrainz.org"
                or port not in {None, 443}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValidationError(
                    "Enter a MusicBrainz release MBID or release URL."
                )
            match = _MUSICBRAINZ_RELEASE_PATH.fullmatch(parsed.path)
            candidate = match.group("mbid") if match else ""
        try:
            parsed_mbid = uuid.UUID(candidate)
        except ValueError as error:
            raise ValidationError(
                "Enter a MusicBrainz release MBID or release URL."
            ) from error
        return str(parsed_mbid)

    async def rebuild(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        current = await self.get(contribution_id)
        if current.state != "stale":
            raise ContributionStateError(
                "Only a stale contribution needs to be rebuilt."
            )
        snapshot = await self._build_local_snapshot(current.local_album_id)
        if snapshot.musicbrainz_release_id:
            raise ContributionStateError(
                "This local album already has an exact MusicBrainz release."
            )
        draft = self._draft_from_snapshot(snapshot)
        row = await self._store.rebuild_library_contribution(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            album_row_revision=snapshot.album_row_revision,
            input_revision=snapshot.input_revision,
            local_snapshot_json=self._encode(snapshot),
            resolved_draft_json=self._encode(draft),
            source_selection_json=self._encode(ContributionSourceSelection()),
            now=time.time(),
        )
        return await self._record(row)

    async def cancel(
        self,
        contribution_id: str,
        *,
        expected_row_revision: int,
        actor_user_id: str,
    ) -> ContributionRecord:
        now = time.time()
        row = await self._store.cancel_library_contribution(
            contribution_id=contribution_id,
            expected_row_revision=expected_row_revision,
            actor_user_id=actor_user_id,
            now=now,
        )
        if await self._purge_provider_data_row(row, now=now):
            row = await self._store.get_library_contribution(contribution_id) or row
        return await self._record(row)

    async def purge_expired_provider_data(
        self, *, now: float | None = None, limit: int = 200
    ) -> int:
        timestamp = time.time() if now is None else now
        rows = await self._store.list_library_contributions_for_provider_purge(
            now=timestamp, limit=limit
        )
        purged = 0
        for row in rows:
            try:
                if await self._purge_provider_data_row(row, now=timestamp):
                    purged += 1
            except ContributionDataError:
                logger.warning(
                    "Skipping malformed contribution %s during provider-data cleanup",
                    row.get("id"),
                    exc_info=True,
                )
        return purged

    async def purge_provider_data(
        self, contribution_id: str, *, now: float | None = None
    ) -> bool:
        row = await self._store.get_library_contribution(contribution_id)
        if row is None:
            return False
        return await self._purge_provider_data_row(
            row, now=time.time() if now is None else now
        )

    async def _purge_provider_data_row(
        self, row: dict[str, Any], *, now: float
    ) -> bool:
        if row.get("provider_snapshot_expires_at") is None:
            return False
        snapshot = self._decode(row["local_snapshot_json"], LocalReleaseSnapshot)
        draft = self._decode(row["resolved_draft_json"], ReleaseDraft)
        selection = self._decode(
            row["source_selection_json"], ContributionSourceSelection
        )
        cleaned_draft = self._without_discogs_values(draft, snapshot)
        cleaned_selection = msgspec.convert(
            msgspec.to_builtins(selection), type=ContributionSourceSelection
        )
        cleaned_selection.alignments = []
        return await self._store.purge_library_contribution_provider_data(
            contribution_id=str(row["id"]),
            expected_row_revision=int(row["row_revision"]),
            resolved_draft_json=self._encode(cleaned_draft),
            source_selection_json=self._encode(cleaned_selection),
            now=now,
        )

    async def _build_local_snapshot(self, album_id: str) -> LocalReleaseSnapshot:
        context = await self._store.get_album_identification_context(album_id)
        if context is None:
            raise ResourceNotFoundError("Library album not found.")
        album = context["album"]
        identity = context.get("identity") or {}
        artist = context.get("artist") or {}
        artist_identity = context.get("artist_identity") or {}
        tracks = [
            track for track in context["tracks"] if track["availability"] == "indexed"
        ]
        if not tracks:
            raise ResourceNotFoundError("Library album not found.")
        input_revision = ":".join(album_input_revisions(tracks))
        grouped: dict[int, list[ReleaseTrackSnapshot]] = defaultdict(list)
        medium_titles: dict[int, str | None] = {}
        for track in tracks:
            disc_number = max(1, int(track["disc_number"] or 1))
            track_number = int(track["track_number"] or 0)
            duration = (
                float(track["duration_seconds"])
                if track["duration_seconds"] is not None
                else None
            )
            grouped[disc_number].append(
                ReleaseTrackSnapshot(
                    local_track_id=str(track["id"]),
                    disc_number=disc_number,
                    track_number=track_number,
                    title=str(track["title"] or ""),
                    artist_name=(
                        str(track["artist_name"])
                        if track["artist_name"] is not None
                        else None
                    ),
                    duration_seconds=duration,
                    duration_reliable=duration is not None and duration > 0,
                )
            )
            medium_titles.setdefault(disc_number, track["disc_subtitle"])
        media = [
            ReleaseMediumSnapshot(
                position=position,
                title=(
                    str(medium_titles[position])
                    if medium_titles[position] is not None
                    else None
                ),
                tracks=sorted(
                    grouped[position],
                    key=lambda item: (item.track_number, item.local_track_id),
                ),
            )
            for position in sorted(grouped)
        ]
        return LocalReleaseSnapshot(
            local_album_id=str(album["id"]),
            local_artist_id=str(album["album_artist_id"]),
            album_row_revision=int(album["row_revision"]),
            input_revision=input_revision,
            title=str(album["title"] or ""),
            album_artist_name=str(album["album_artist_name"] or ""),
            artist_kind=str(artist.get("kind") or "unknown"),
            musicbrainz_artist_id=artist_identity.get("provider_artist_id"),
            musicbrainz_release_group_id=identity.get("release_group_mbid"),
            musicbrainz_release_id=identity.get("release_mbid"),
            release_date=(
                str(album["original_release_date"])
                if album["original_release_date"]
                else None
            ),
            year=int(album["year"]) if album["year"] is not None else None,
            is_compilation=bool(album["is_compilation"]),
            captured_at=time.time(),
            media=media,
        )

    @staticmethod
    def _draft_from_snapshot(snapshot: LocalReleaseSnapshot) -> ReleaseDraft:
        return ReleaseDraft(
            title=ReleaseTextField(value=snapshot.title),
            artist_credit=ReleaseTextField(value=snapshot.album_artist_name),
            release_date=ReleaseTextField(
                value=snapshot.release_date
                or (str(snapshot.year) if snapshot.year is not None else None)
            ),
            media=[
                ReleaseMediumDraft(
                    position=medium.position,
                    title=ReleaseTextField(value=medium.title),
                    tracks=[
                        ReleaseTrackDraft(
                            local_track_id=track.local_track_id,
                            disc_number=track.disc_number,
                            track_number=track.track_number,
                            title=ReleaseTextField(value=track.title),
                            artist_name=ReleaseTextField(value=track.artist_name),
                            duration_seconds=track.duration_seconds,
                        )
                        for track in medium.tracks
                    ],
                )
                for medium in snapshot.media
            ],
        )

    def _normalize_draft(
        self,
        draft: ReleaseDraft,
        snapshot: LocalReleaseSnapshot,
        selection: ContributionSourceSelection,
        discogs_release: DiscogsRelease | None,
    ) -> ReleaseDraft:
        if draft.schema_version != 1:
            raise ValidationError("Unsupported contribution draft version.")
        snapshot_tracks = {
            track.local_track_id: track
            for medium in snapshot.media
            for track in medium.tracks
        }
        draft_tracks = [track for medium in draft.media for track in medium.tracks]
        if len(draft_tracks) != len(snapshot_tracks) or {
            track.local_track_id for track in draft_tracks
        } != set(snapshot_tracks):
            raise ValidationError(
                "The contribution track list does not match the album."
            )
        seen: set[str] = set()
        for track in draft_tracks:
            if track.local_track_id in seen:
                raise ValidationError("A contribution track may only appear once.")
            seen.add(track.local_track_id)
            source = snapshot_tracks[track.local_track_id]
            if (
                track.disc_number != source.disc_number
                or track.track_number != source.track_number
            ):
                raise ValidationError("Track positions cannot be changed in this step.")
        self._validate_local_provenance(
            draft, snapshot, snapshot_tracks, selection, discogs_release
        )
        return msgspec.convert(
            self._trim_strings(msgspec.to_builtins(draft)), type=ReleaseDraft
        )

    @staticmethod
    def _trim_strings(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if len(stripped) > _MAX_TEXT_LENGTH:
                raise ValidationError("A contribution value is too long.")
            return stripped
        if isinstance(value, list):
            return [LibraryContributionService._trim_strings(item) for item in value]
        if isinstance(value, dict):
            return {
                key: LibraryContributionService._trim_strings(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _validate_local_provenance(
        draft: ReleaseDraft,
        snapshot: LocalReleaseSnapshot,
        snapshot_tracks: dict[str, ReleaseTrackSnapshot],
        selection: ContributionSourceSelection,
        discogs_release: DiscogsRelease | None,
    ) -> None:
        local_fields = (
            (draft.title, snapshot.title),
            (draft.artist_credit, snapshot.album_artist_name),
            (
                draft.release_date,
                snapshot.release_date
                or (str(snapshot.year) if snapshot.year is not None else None),
            ),
        )
        optional_fields = (
            draft.country,
            draft.label,
            draft.catalogue_number,
            draft.barcode,
            draft.packaging,
        )
        for field, local_value in local_fields:
            if field.source == "local" and field.value != local_value:
                raise ValidationError("A changed value must be marked as entered here.")
        for field in optional_fields:
            if field.source == "local" and field.value is not None:
                raise ValidationError("This value was not present in local metadata.")
        for track in (track for medium in draft.media for track in medium.tracks):
            local = snapshot_tracks[track.local_track_id]
            for field, local_value in (
                (track.title, local.title),
                (track.artist_name, local.artist_name),
            ):
                if field.source == "local" and field.value != local_value:
                    raise ValidationError(
                        "A changed track value must be marked as entered here."
                    )
        if any(
            field.source == "discogs"
            for field in LibraryContributionService._draft_fields(draft)
        ):
            if discogs_release is None:
                raise ContributionProviderExpiredError(
                    "Refresh the Discogs source before using its values."
                )
            LibraryContributionService._validate_discogs_values(
                draft, selection, discogs_release
            )

    @staticmethod
    def _draft_fields(draft: ReleaseDraft) -> list[ReleaseTextField]:
        fields = [
            draft.title,
            draft.artist_credit,
            draft.release_date,
            draft.country,
            draft.label,
            draft.catalogue_number,
            draft.barcode,
            draft.packaging,
        ]
        for medium in draft.media:
            fields.extend((medium.title, medium.format))
            for track in medium.tracks:
                fields.extend((track.title, track.artist_name))
        return fields

    @staticmethod
    def _validate_discogs_values(
        draft: ReleaseDraft,
        selection: ContributionSourceSelection,
        release: DiscogsRelease,
    ) -> None:
        label = release.labels[0] if release.labels else None
        allowed: list[tuple[ReleaseTextField, str | None]] = [
            (draft.title, release.title),
            (draft.artist_credit, release.artist_name),
            (draft.release_date, release.released_date),
            (draft.country, release.country),
            (draft.label, label.name if label else None),
            (draft.catalogue_number, label.catalogue_number if label else None),
            (draft.barcode, release.barcode),
        ]
        for field, value in allowed:
            if field.source == "discogs" and field.value != value:
                raise ValidationError(
                    "A Discogs value must match the selected Discogs release."
                )
        if draft.packaging.source == "discogs":
            raise ValidationError("Discogs did not provide a verified packaging value.")
        provider_media = {medium.position: medium for medium in release.media}
        alignment_by_track = {
            item.local_track_id: item for item in selection.alignments
        }
        for medium in draft.media:
            provider_medium = provider_media.get(medium.position)
            if medium.title.source == "discogs":
                expected = provider_medium.title if provider_medium else None
                if medium.title.value != expected:
                    raise ValidationError("The Discogs medium title does not match.")
            if medium.format.source == "discogs":
                expected = provider_medium.format if provider_medium else None
                if medium.format.value != expected:
                    raise ValidationError("The Discogs medium format does not match.")
            for track in medium.tracks:
                alignment = alignment_by_track.get(track.local_track_id)
                provider_track = None
                if alignment and alignment.provider_position and provider_medium:
                    provider_track = next(
                        (
                            item
                            for item in provider_medium.tracks
                            if item.source_position == alignment.provider_position
                            and not item.heading
                        ),
                        None,
                    )
                if track.title.source == "discogs" and (
                    provider_track is None or track.title.value != provider_track.title
                ):
                    raise ValidationError("The Discogs track title does not match.")
                if track.artist_name.source == "discogs":
                    expected_artist = (
                        provider_track.artists[0].credited_name
                        or provider_track.artists[0].name
                        if provider_track and provider_track.artists
                        else release.artist_name
                    )
                    if track.artist_name.value != expected_artist:
                        raise ValidationError(
                            "The Discogs track artist does not match."
                        )

    @staticmethod
    def _duplicate_candidate(
        contribution: ContributionRecord,
        verified: MusicBrainzVerifiedRelease | None,
        *,
        release_mbid: str,
        evidence_kind: Literal[
            "exact_discogs_url", "release_group", "barcode", "similar"
        ],
        exact: bool,
    ) -> DuplicateCandidate:
        differences: list[str] = []
        draft = contribution.draft
        if verified is not None:
            comparisons = (
                ("title", draft.title.value, verified.title),
                ("artist", draft.artist_credit.value, verified.artist_name),
                ("date", draft.release_date.value, verified.date),
                ("country", draft.country.value, verified.country),
                ("label", draft.label.value, verified.label),
                (
                    "catalogue number",
                    draft.catalogue_number.value,
                    verified.catalogue_number,
                ),
                ("barcode", draft.barcode.value, verified.barcode),
            )
            for name, proposed, existing in comparisons:
                if proposed and existing and proposed.casefold() != existing.casefold():
                    differences.append(f"Different {name}: {existing}")
            local_track_count = sum(len(medium.tracks) for medium in draft.media)
            if verified.tracks and len(verified.tracks) != local_track_count:
                differences.append(
                    f"Different track count: {len(verified.tracks)} on MusicBrainz"
                )
        return DuplicateCandidate(
            release_mbid=release_mbid,
            release_group_mbid=(verified.release_group_mbid if verified else None),
            title=verified.title if verified else draft.title.value or "",
            artist_name=(
                verified.artist_name if verified else draft.artist_credit.value or ""
            ),
            evidence_kind=evidence_kind,
            exact=exact,
            differences=differences,
        )

    def _attachment_evidence(
        self,
        contribution: ContributionRecord,
        verified: MusicBrainzVerifiedRelease,
        *,
        recording_mbids: dict[str, str | None] | None = None,
    ) -> IdentificationDecision:
        draft_tracks = {
            track.local_track_id: track
            for medium in contribution.draft.media
            for track in medium.tracks
        }
        local_tracks = [
            GroupingTrack(
                local_track_id=track.local_track_id,
                root_id="",
                relative_path="",
                title=(draft_tracks[track.local_track_id].title.value or track.title),
                artist_name=(
                    draft_tracks[track.local_track_id].artist_name.value
                    or track.artist_name
                    or ""
                ),
                album_title=contribution.draft.title.value or "",
                album_artist_name=contribution.draft.artist_credit.value or "",
                track_number=track.track_number,
                disc_number=track.disc_number,
                duration_seconds=track.duration_seconds,
                recording_mbid=(recording_mbids or {}).get(track.local_track_id),
                is_compilation=contribution.local_snapshot.is_compilation,
                current_album_id=contribution.local_album_id,
            )
            for medium in contribution.local_snapshot.media
            for track in medium.tracks
        ]
        candidate = AlbumCandidate(
            release_group_mbid=verified.release_group_mbid,
            release_mbid=verified.release_mbid,
            album_title=verified.title,
            album_artist_name=verified.artist_name,
            tracks=[
                CandidateTrack(
                    title=track.title,
                    position=track.position,
                    disc_number=track.disc_number,
                    absolute_position=index + 1,
                    duration_seconds=track.duration_seconds,
                    recording_mbid=track.recording_mbid,
                )
                for index, track in enumerate(verified.tracks)
            ],
            artist_mbid=verified.artist_mbid,
            release_date=verified.date,
            source_kinds=["musicbrainz_verification", "contribution_duplicate"],
        )
        return self._evidence.decide(local_tracks, [candidate])

    async def _musicbrainz_seed_fields(
        self,
        contribution: ContributionRecord,
        *,
        discogs_release: DiscogsRelease | None,
        redirect_uri: str,
    ) -> list[MusicBrainzSeedField]:
        draft = contribution.draft
        fields = [MusicBrainzSeedField(name="name", value=draft.title.value or "")]
        discovered_group_ids = list(
            dict.fromkeys(
                candidate.release_group_mbid
                for candidate in (
                    contribution.duplicate_result.candidates
                    if contribution.duplicate_result
                    else []
                )
                if candidate.evidence_kind == "release_group"
                and candidate.release_group_mbid
            )
        )
        group_ids = (
            [contribution.local_snapshot.musicbrainz_release_group_id]
            if contribution.local_snapshot.musicbrainz_release_group_id
            else discovered_group_ids
        )
        if len(group_ids) == 1:
            fields.append(
                MusicBrainzSeedField(name="release_group", value=group_ids[0])
            )
        if draft.barcode.value:
            fields.append(
                MusicBrainzSeedField(name="barcode", value=draft.barcode.value)
            )
        if draft.packaging.value:
            fields.append(
                MusicBrainzSeedField(name="packaging", value=draft.packaging.value)
            )
        date_parts = (draft.release_date.value or "").split("-")
        if date_parts and len(date_parts[0]) == 4 and date_parts[0].isdigit():
            fields.append(
                MusicBrainzSeedField(name="events.0.date.year", value=date_parts[0])
            )
            if (
                len(date_parts) > 1
                and date_parts[1].isdigit()
                and date_parts[1] != "00"
            ):
                fields.append(
                    MusicBrainzSeedField(
                        name="events.0.date.month", value=str(int(date_parts[1]))
                    )
                )
            if (
                len(date_parts) > 2
                and date_parts[2].isdigit()
                and date_parts[2] != "00"
            ):
                fields.append(
                    MusicBrainzSeedField(
                        name="events.0.date.day", value=str(int(date_parts[2]))
                    )
                )
        country = draft.country.value
        if country:
            normalized_country = {"UK": "GB"}.get(country.upper(), country.upper())
            if len(normalized_country) == 2 and normalized_country.isalpha():
                fields.append(
                    MusicBrainzSeedField(
                        name="events.0.country", value=normalized_country
                    )
                )
        if draft.label.value or draft.catalogue_number.value:
            if draft.label.value:
                fields.append(
                    MusicBrainzSeedField(name="labels.0.name", value=draft.label.value)
                )
            if draft.catalogue_number.value:
                fields.append(
                    MusicBrainzSeedField(
                        name="labels.0.catalog_number",
                        value=draft.catalogue_number.value,
                    )
                )
        artist_name = draft.artist_credit.value or ""
        if contribution.local_snapshot.musicbrainz_artist_id:
            fields.append(
                MusicBrainzSeedField(
                    name="artist_credit.names.0.mbid",
                    value=contribution.local_snapshot.musicbrainz_artist_id,
                )
            )
        fields.extend(
            (
                MusicBrainzSeedField(
                    name="artist_credit.names.0.artist.name", value=artist_name
                ),
                MusicBrainzSeedField(
                    name="artist_credit.names.0.name", value=artist_name
                ),
            )
        )
        context = await self._store.get_album_identification_context(
            contribution.local_album_id
        )
        recording_ids = {
            str(track["id"]): str(track["recording_mbid"])
            for track in (context["tracks"] if context else [])
            if track.get("recording_mbid")
        }
        for medium_index, medium in enumerate(draft.media):
            if medium.format.value:
                fields.append(
                    MusicBrainzSeedField(
                        name=f"mediums.{medium_index}.format",
                        value=medium.format.value,
                    )
                )
            if medium.title.value:
                fields.append(
                    MusicBrainzSeedField(
                        name=f"mediums.{medium_index}.name", value=medium.title.value
                    )
                )
            for track_index, track in enumerate(medium.tracks):
                prefix = f"mediums.{medium_index}.track.{track_index}"
                fields.extend(
                    (
                        MusicBrainzSeedField(
                            name=f"{prefix}.name", value=track.title.value or ""
                        ),
                        MusicBrainzSeedField(
                            name=f"{prefix}.number", value=str(track.track_number)
                        ),
                    )
                )
                if track.duration_seconds is not None and track.duration_seconds > 0:
                    fields.append(
                        MusicBrainzSeedField(
                            name=f"{prefix}.length",
                            value=str(round(track.duration_seconds * 1000)),
                        )
                    )
                recording_mbid = recording_ids.get(track.local_track_id)
                if recording_mbid:
                    fields.append(
                        MusicBrainzSeedField(
                            name=f"{prefix}.recording", value=recording_mbid
                        )
                    )
                track_artist = track.artist_name.value
                if track_artist and track_artist != artist_name:
                    fields.extend(
                        (
                            MusicBrainzSeedField(
                                name=f"{prefix}.artist_credit.names.0.artist.name",
                                value=track_artist,
                            ),
                            MusicBrainzSeedField(
                                name=f"{prefix}.artist_credit.names.0.name",
                                value=track_artist,
                            ),
                        )
                    )
        if discogs_release is not None:
            fields.extend(
                (
                    MusicBrainzSeedField(
                        name="urls.0.url", value=discogs_release.canonical_release_url
                    ),
                    MusicBrainzSeedField(
                        name="urls.0.link_type",
                        value=_MUSICBRAINZ_DISCOGS_RELEASE_LINK_TYPE,
                    ),
                )
            )
        edit_note = (
            "Seeded with DroppedNeedle "
            "(https://github.com/DroppedNeedle/DroppedNeedle).\nSources:\n"
            "* Local audio-file metadata"
        )
        if discogs_release is not None:
            edit_note += f"\n* Discogs release: {discogs_release.canonical_release_url}"
        fields.append(MusicBrainzSeedField(name="edit_note", value=edit_note))
        fields.append(MusicBrainzSeedField(name="redirect_uri", value=redirect_uri))
        return fields

    def _require_musicbrainz(self) -> MusicBrainzRepositoryProtocol:
        if self._musicbrainz is None:
            raise ContributionDataError("The MusicBrainz adapter is not available.")
        return self._musicbrainz

    async def _invalidate_catalog_cache(self) -> None:
        if self._cache is None:
            return
        for prefix in library_identification_prefixes():
            await self._cache.clear_prefix(prefix)

    @staticmethod
    def _validate(
        draft: ReleaseDraft, snapshot: LocalReleaseSnapshot
    ) -> list[ContributionValidationIssue]:
        issues: list[ContributionValidationIssue] = []
        if not draft.title.value:
            issues.append(
                ContributionValidationIssue(
                    code="RELEASE_TITLE_REQUIRED",
                    field="title",
                    message="Add a release title.",
                )
            )
        if not draft.artist_credit.value:
            issues.append(
                ContributionValidationIssue(
                    code="ARTIST_CREDIT_REQUIRED",
                    field="artist_credit",
                    message="Add an artist credit.",
                )
            )
        elif (
            snapshot.artist_kind == "unknown"
            and draft.artist_credit.value.casefold()
            == snapshot.album_artist_name.casefold()
        ):
            issues.append(
                ContributionValidationIssue(
                    code="ARTIST_CREDIT_PLACEHOLDER",
                    field="artist_credit",
                    message="Replace the Unknown Artist placeholder with a real artist credit.",
                )
            )
        if (
            snapshot.artist_kind == "various_artists"
            and not snapshot.musicbrainz_artist_id
        ):
            issues.append(
                ContributionValidationIssue(
                    code="VARIOUS_ARTISTS_IDENTITY_REQUIRED",
                    field="artist_credit",
                    message="Link Various Artists to MusicBrainz before contributing this release.",
                )
            )
        if not draft.media:
            issues.append(
                ContributionValidationIssue(
                    code="TRACKS_REQUIRED",
                    field="media",
                    message="At least one track is required.",
                )
            )
        for medium_index, medium in enumerate(draft.media):
            if not medium.tracks:
                issues.append(
                    ContributionValidationIssue(
                        code="MEDIUM_TRACKS_REQUIRED",
                        field=f"media.{medium_index}.tracks",
                        message="Each medium needs at least one track.",
                    )
                )
            for track_index, track in enumerate(medium.tracks):
                if not track.title.value:
                    issues.append(
                        ContributionValidationIssue(
                            code="TRACK_TITLE_REQUIRED",
                            field=f"media.{medium_index}.tracks.{track_index}.title",
                            message="Add a track title.",
                        )
                    )
        if snapshot.schema_version != 1:
            raise ContributionDataError("Unsupported local contribution snapshot.")
        return issues

    @staticmethod
    def parse_discogs_release_id(value: str) -> str:
        candidate = value.strip()
        if candidate.isdigit() and int(candidate) > 0:
            return str(int(candidate))
        try:
            parsed = urlsplit(candidate)
        except ValueError as error:
            raise ValidationError(
                "Enter a valid Discogs release URL or numeric ID."
            ) from error
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _DISCOGS_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError("Enter a valid Discogs release URL or numeric ID.")
        match = _DISCOGS_RELEASE_PATH.fullmatch(parsed.path)
        if match is None:
            raise ValidationError(
                "Enter an exact Discogs release URL, not a master URL."
            )
        return str(int(match.group("id")))

    def _require_discogs(self) -> DiscogsRepositoryProtocol:
        if self._discogs is None:
            raise ContributionDataError("The Discogs adapter is not available.")
        return self._discogs

    async def _current_discogs_release(
        self, contribution: ContributionRecord
    ) -> DiscogsRelease | None:
        source = next(
            (
                item
                for item in contribution.source_selection.sources
                if item.provider == "discogs" and item.entity_type == "release"
            ),
            None,
        )
        if source is None:
            return None
        expires_at = contribution.provider_snapshot_expires_at
        if expires_at is None or expires_at <= time.time():
            return None
        return await self._require_discogs().get_release(
            source.external_id, priority=RequestPriority.USER_INITIATED
        )

    @staticmethod
    def _normalized_title(value: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())

    @classmethod
    def _align_tracks(
        cls, snapshot: LocalReleaseSnapshot, release: DiscogsRelease
    ) -> list[TrackAlignment]:
        provider_tracks = [
            (medium.position, track)
            for medium in release.media
            for track in medium.tracks
            if not track.heading
        ]
        used: set[int] = set()
        alignments: list[TrackAlignment] = []
        for local in (track for medium in snapshot.media for track in medium.tracks):
            best_index: int | None = None
            best_score = -1.0
            for index, (medium_position, provider) in enumerate(provider_tracks):
                if index in used:
                    continue
                position_score = (
                    1.0
                    if (
                        medium_position == local.disc_number
                        and provider.number == local.track_number
                    )
                    else 0.0
                )
                title_score = SequenceMatcher(
                    None,
                    cls._normalized_title(local.title),
                    cls._normalized_title(provider.title),
                ).ratio()
                duration_score = 0.0
                if (
                    local.duration_reliable
                    and local.duration_seconds is not None
                    and provider.duration_seconds is not None
                ):
                    duration_score = max(
                        0.0,
                        1.0
                        - abs(local.duration_seconds - provider.duration_seconds)
                        / 10.0,
                    )
                score = (
                    position_score * 0.45 + title_score * 0.45 + duration_score * 0.1
                )
                if score > best_score:
                    best_index = index
                    best_score = score
            if best_index is None or best_score < 0.45:
                alignments.append(
                    TrackAlignment(
                        local_track_id=local.local_track_id,
                        classification="unmatched",
                    )
                )
                continue
            used.add(best_index)
            _medium_position, provider = provider_tracks[best_index]
            local_title = cls._normalized_title(local.title)
            provider_title = cls._normalized_title(provider.title)
            position_matches = (
                _medium_position == local.disc_number
                and provider.number == local.track_number
            )
            if position_matches and local_title == provider_title:
                classification = "exact"
            elif best_score >= 0.68:
                classification = "partial"
            else:
                classification = "conflicting"
            alignments.append(
                TrackAlignment(
                    local_track_id=local.local_track_id,
                    provider_position=provider.source_position,
                    classification=classification,
                )
            )
        return alignments

    @staticmethod
    def _without_discogs_values(
        draft: ReleaseDraft, snapshot: LocalReleaseSnapshot
    ) -> ReleaseDraft:
        result = msgspec.convert(msgspec.to_builtins(draft), type=ReleaseDraft)
        local_draft = LibraryContributionService._draft_from_snapshot(snapshot)
        top_fields = (
            (result.title, local_draft.title),
            (result.artist_credit, local_draft.artist_credit),
            (result.release_date, local_draft.release_date),
            (result.country, local_draft.country),
            (result.label, local_draft.label),
            (result.catalogue_number, local_draft.catalogue_number),
            (result.barcode, local_draft.barcode),
            (result.packaging, local_draft.packaging),
        )
        for field, local in top_fields:
            if field.source == "discogs":
                field.value = local.value
                field.source = "local"
        local_media = {medium.position: medium for medium in local_draft.media}
        for medium in result.media:
            local_medium = local_media[medium.position]
            for field, local in (
                (medium.title, local_medium.title),
                (medium.format, local_medium.format),
            ):
                if field.source == "discogs":
                    field.value = local.value
                    field.source = "local"
            local_tracks = {
                track.local_track_id: track for track in local_medium.tracks
            }
            for track in medium.tracks:
                local_track = local_tracks[track.local_track_id]
                for field, local in (
                    (track.title, local_track.title),
                    (track.artist_name, local_track.artist_name),
                ):
                    if field.source == "discogs":
                        field.value = local.value
                        field.source = "local"
        return result

    @staticmethod
    def _redact_expired_discogs(draft: ReleaseDraft) -> ReleaseDraft:
        result = msgspec.convert(msgspec.to_builtins(draft), type=ReleaseDraft)
        for field in LibraryContributionService._draft_fields(result):
            if field.source == "discogs":
                field.value = None
        return result

    async def _record(
        self,
        row: dict[str, Any],
        *,
        discogs_release: DiscogsRelease | None = None,
    ) -> ContributionRecord:
        snapshot = self._decode(row["local_snapshot_json"], LocalReleaseSnapshot)
        draft = self._decode(row["resolved_draft_json"], ReleaseDraft)
        selection = self._decode(
            row["source_selection_json"], ContributionSourceSelection
        )
        if (
            snapshot.schema_version != 1
            or draft.schema_version != 1
            or selection.schema_version != 1
        ):
            raise ContributionDataError("Unsupported persisted contribution document.")
        discogs_source_ref = next(
            (
                source
                for source in selection.sources
                if source.provider == "discogs" and source.entity_type == "release"
            ),
            None,
        )
        expires_at = row.get("provider_snapshot_expires_at")
        discogs_expired = bool(
            discogs_source_ref is not None
            and (expires_at is None or float(expires_at) <= time.time())
        )
        if discogs_expired:
            draft = self._redact_expired_discogs(draft)
        elif (
            discogs_source_ref is not None and discogs_release is None and self._discogs
        ):
            discogs_release = await self._discogs.get_release(
                discogs_source_ref.external_id,
                priority=RequestPriority.USER_INITIATED,
            )
        issues = self._validate(draft, snapshot)
        input_is_current = not self._row_is_stale(row)
        state = str(row["state"])
        duplicate = (
            self._decode_duplicate(row["duplicate_result_json"])
            if row.get("duplicate_result_json")
            else None
        )
        next_actions: list[str] = []
        if state == "stale":
            if row.get("album_active", True):
                next_actions.append("rebuild")
        elif state == "seeded":
            next_actions.extend(("seed_musicbrainz", "cancel"))
        elif state == "needs_review" and row.get("result_release_mbid"):
            next_actions.extend(("retry_verification", "cancel"))
        elif state not in {"linked", "cancelled"}:
            if state in {"draft", "ready", "needs_review"}:
                next_actions.append("edit_draft")
                if discogs_expired:
                    next_actions.append("refresh_discogs")
                elif not issues:
                    next_actions.append("run_duplicate_check")
                if duplicate is not None:
                    exact = [
                        candidate
                        for candidate in duplicate.candidates
                        if candidate.exact
                    ]
                    if len(exact) == 1:
                        next_actions.append("attach_existing")
                    elif state == "ready" and not exact:
                        next_actions.append("seed_musicbrainz")
            next_actions.append("cancel")
        return ContributionRecord(
            id=str(row["id"]),
            local_album_id=str(row["local_album_id"]),
            created_by_user_id=row.get("created_by_user_id"),
            updated_by_user_id=row.get("updated_by_user_id"),
            state=state,
            album_row_revision=int(row["album_row_revision"]),
            input_revision=str(row["input_revision"]),
            local_snapshot=snapshot,
            draft=draft,
            source_selection=selection,
            provider_snapshot_expires_at=row.get("provider_snapshot_expires_at"),
            discogs_source=(
                DiscogsSourceView(
                    release=discogs_release if not discogs_expired else None,
                    expired=discogs_expired,
                    expires_at=expires_at,
                )
                if discogs_source_ref is not None
                else None
            ),
            duplicate_result=duplicate,
            duplicate_checked_at=row.get("duplicate_checked_at"),
            result_release_mbid=row.get("result_release_mbid"),
            result_source=row.get("result_source"),
            result_received_at=row.get("result_received_at"),
            seeded_at=row.get("seeded_at"),
            terminal_at=row.get("terminal_at"),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            row_revision=int(row["row_revision"]),
            input_is_current=input_is_current,
            validation=issues,
            next_actions=next_actions,
        )

    @staticmethod
    def _row_is_stale(row: dict[str, Any]) -> bool:
        return not bool(row.get("album_active", True)) or (
            row.get("current_input_revision") != row.get("input_revision")
            or row.get("current_album_row_revision") != row.get("album_row_revision")
        )

    @staticmethod
    def _encode(document: msgspec.Struct) -> str:
        return msgspec.json.encode(document).decode()

    @staticmethod
    def _decode(value: str, document_type: type[_Document]) -> _Document:
        try:
            return msgspec.json.decode(value.encode(), type=document_type)
        except (msgspec.DecodeError, msgspec.ValidationError) as error:
            raise ContributionDataError(
                "A persisted contribution document could not be decoded."
            ) from error

    @staticmethod
    def _decode_duplicate(value: str):
        from models.library_contribution import DuplicateCheckResult

        return LibraryContributionService._decode(value, DuplicateCheckResult)
