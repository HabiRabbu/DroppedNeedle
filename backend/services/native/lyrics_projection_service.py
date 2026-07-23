"""Accuracy-gated LRCLIB projection for Library Management."""

from __future__ import annotations

import math
import unicodedata

from api.v1.schemas.library_management import LyricsManagementSettings
from core.exceptions import ExternalServiceError, RateLimitedError
from infrastructure.audio.lyrics import normalize_lrc
from models.library_management_canonical import (
    CanonicalReleaseDocument,
    CanonicalTrackDocument,
)
from models.library_management_enrichment import LyricsProjection
from repositories.protocols.lrclib import LrclibRepositoryProtocol

_DURATION_TOLERANCE_SECONDS = 2.0


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _artist_credit(credits) -> str:  # noqa: ANN001
    return "".join(f"{credit.display_name}{credit.join_phrase}" for credit in credits)


class LyricsProjectionService:
    def __init__(self, repository: LrclibRepositoryProtocol) -> None:
        self._repository = repository

    async def project(
        self,
        *,
        settings: LyricsManagementSettings,
        canonical_release: CanonicalReleaseDocument,
        canonical_track: CanonicalTrackDocument,
        duration_seconds: float,
    ) -> LyricsProjection:
        if not settings.enabled:
            return LyricsProjection(status="disabled")
        artist_name = _artist_credit(canonical_track.artist_credits).strip()
        if (
            not canonical_track.title.strip()
            or not artist_name
            or not canonical_release.title.strip()
            or not math.isfinite(duration_seconds)
            or duration_seconds <= 0
        ):
            return LyricsProjection(
                status="mismatch",
                reason="The exact lyrics signature is incomplete.",
            )
        requested_duration = int(round(duration_seconds))
        try:
            result = await self._repository.get_exact_lyrics(
                track_name=canonical_track.title,
                artist_name=artist_name,
                album_name=canonical_release.title,
                duration_seconds=requested_duration,
            )
        except (ExternalServiceError, RateLimitedError):
            return LyricsProjection(
                status="deferred",
                reason="The lyrics provider is temporarily unavailable.",
            )
        candidate = result.candidate
        if not result.found or candidate is None:
            return LyricsProjection(
                status="not_found",
                reason="No exact LRCLIB match was found.",
            )
        expected = (
            _normalized(canonical_track.title),
            _normalized(artist_name),
            _normalized(canonical_release.title),
        )
        received = (
            _normalized(candidate.track_name),
            _normalized(candidate.artist_name),
            _normalized(candidate.album_name),
        )
        if expected != received or (
            abs(candidate.duration_seconds - duration_seconds)
            > _DURATION_TOLERANCE_SECONDS
        ):
            return LyricsProjection(
                status="mismatch",
                provider_id=candidate.provider_id,
                provider_revision=candidate.provider_revision,
                reason="LRCLIB returned a different recording signature.",
            )
        return LyricsProjection(
            status="available",
            plain_lyrics=candidate.plain_lyrics,
            synced_lyrics=(
                normalize_lrc(candidate.synced_lyrics)
                if candidate.synced_lyrics
                else None
            ),
            provider_id=candidate.provider_id,
            provider_revision=candidate.provider_revision,
        )
