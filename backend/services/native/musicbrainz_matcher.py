"""MusicBrainzMatcher - Tier 2 (text) identification.

Wraps the existing ``MusicBrainzRepository`` to identify an album by fuzzy
text match (``rapidfuzz.token_set_ratio``) when the file's tags carry no usable
MusicBrainz IDs. Tier 1 (MBIDs in tags) is handled directly by the scanner;
Tier 3 resolves an AcoustID recording MBID to a release group via
``resolve_recording_to_release_group`` (added in Phase 4).

(AUD-13) The matcher owns **no** rate limiter and makes **no** raw MB HTTP
calls - every lookup goes through ``MusicBrainzRepository``, which already
applies the module-global limiter + circuit breaker + retry + dedup.
"""

import logging
import re
from typing import TYPE_CHECKING

from rapidfuzz.distance import Levenshtein
from rapidfuzz.fuzz import token_set_ratio
from unidecode import unidecode

from infrastructure.msgspec_fastapi import AppStruct

if TYPE_CHECKING:
    from repositories.musicbrainz_album import RecordingReleaseGroup
    from repositories.musicbrainz_repository import MusicBrainzRepository

logger = logging.getLogger(__name__)

# Confidence at/above which Tier 2 auto-accepts (0-1 scale).
TEXT_MATCH_THRESHOLD = 0.85

_RG_TITLE_DISAMBIGUATION = 0.5

_EDITION_SUFFIXES = re.compile(
    r"\b(deluxe|remastered|remaster|edition|anniversary|special|expanded|"
    r"complete|bonus|acoustic|live|demo|radio edit|extended|instrumental|"
    r"mono|stereo|explicit|clean|version|single|promo)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"[\(\)\[\]{}]")
_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

# CJK / Kana ranges - strings containing these must NOT be transliterated.
_CJK = re.compile(r"[一-鿿぀-ゟ゠-ヿ]")


class TargetAlbum(AppStruct):
    artist: str
    album: str
    year: int | None = None
    track_title: str | None = None
    track_number: int | None = None
    duration_seconds: float | None = None


class MatchResult(AppStruct):
    confidence: float
    release_group_mbid: str | None = None
    release_mbid: str | None = None
    recording_mbids: dict[int, str] = {}
    recording_mbid: str | None = None

    @property
    def matched(self) -> bool:
        return self.confidence >= TEXT_MATCH_THRESHOLD and self.release_group_mbid is not None


class MusicBrainzMatcher:
    # A candidate whose artist similarity falls below this is rejected outright,
    # so a same-titled album by a different artist can't auto-accept.
    ARTIST_MATCH_FLOOR = 0.6

    def __init__(self, mb_repo: "MusicBrainzRepository") -> None:
        self._mb_repo = mb_repo

    @staticmethod
    def is_cjk(text: str) -> bool:
        return bool(_CJK.search(text))

    @classmethod
    def _fold(cls, text: str) -> str:
        """Transliterate diacritics to ASCII for fuzzy matching (so 'Björk'
        matches 'Bjork'), but never CJK/Kana - transliterating those is lossy and
        hurts matching (D3). File paths keep the original NFC form; this folding is
        comparison-only."""
        return text if cls.is_cjk(text) else unidecode(text)

    @classmethod
    def _normalize(cls, text: str) -> str:
        """Case- and punctuation-fold for fuzzy comparison."""
        folded = cls._fold(text).lower()
        return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", folded)).strip()

    @classmethod
    def _strip_edition_suffix(cls, title: str) -> str:
        """Remove edition qualifiers + leftover brackets, collapse whitespace."""
        stripped = _EDITION_SUFFIXES.sub("", title)
        stripped = _BRACKETS.sub(" ", stripped)
        return _WHITESPACE.sub(" ", stripped).strip()

    @classmethod
    def title_similarity(cls, a: str, b: str) -> float:
        """0-1 fuzzy similarity of two album titles, edition-suffix- and case-insensitive."""
        na = cls._normalize(cls._strip_edition_suffix(a))
        nb = cls._normalize(cls._strip_edition_suffix(b))
        if not na or not nb:
            return 0.0
        return token_set_ratio(na, nb) / 100.0

    def _artist_floor_ok(self, target_artist: str, candidate_artist: str | None) -> bool:
        """True unless the candidate's artist clearly mismatches the target's."""
        if not candidate_artist:
            return True
        result_artist = self._normalize(candidate_artist)
        if not result_artist:
            return True
        return (
            token_set_ratio(self._normalize(target_artist), result_artist) / 100.0
            >= self.ARTIST_MATCH_FLOOR
        )

    async def text_match(self, target: TargetAlbum) -> MatchResult:
        """Tier 2. Match on artist+album title, falling back to recording (track) match."""
        album = await self._album_text_match(target)
        if album.matched:
            return album
        if target.track_title:
            recording = await self._recording_match(target)
            if recording.matched:
                return recording
        return album

    async def _album_text_match(self, target: TargetAlbum) -> MatchResult:
        query = f"{target.artist} {target.album}".strip()
        results = await self._mb_repo.search_albums(query, limit=10, include_all_types=True)
        best_score = (0.0, 0.0)
        best_mbid: str | None = None
        for result in results:
            if not result.musicbrainz_id:
                continue
            if not self._artist_floor_ok(target.artist, result.artist):
                continue
            # Rank by similarity, breaking ties by title exactness.
            score = (
                self.title_similarity(target.album, result.title),
                self._title_specificity(target.album, result.title),
            )
            if score > best_score:
                best_score = score
                best_mbid = result.musicbrainz_id
        # Gate the mbid on the same rounded value reported as confidence, so the
        # two never disagree at the threshold boundary.
        confidence = round(best_score[0], 4)
        return MatchResult(
            confidence=confidence,
            release_group_mbid=best_mbid if confidence >= TEXT_MATCH_THRESHOLD else None,
        )

    @classmethod
    def _title_specificity(cls, a: str, b: str) -> float:
        """Length-sensitive title similarity used to break ``title_similarity`` ties."""
        na = cls._normalize(cls._strip_edition_suffix(a))
        nb = cls._normalize(cls._strip_edition_suffix(b))
        if not na or not nb:
            return 0.0
        return Levenshtein.normalized_similarity(na, nb)

    @staticmethod
    def _rg_rank(rg: "RecordingReleaseGroup") -> int:
        """Prefer a studio Album over EP/Single, penalising secondary types."""
        primary = {"Album": 3, "EP": 2, "Single": 1}.get(rg.primary_type or "", 0)
        return primary - 1 if rg.secondary_types else primary

    def _select_release_group(
        self, album: str, groups: list["RecordingReleaseGroup"]
    ) -> "RecordingReleaseGroup":
        """Pick which of a recording's release groups the file belongs to."""
        if album.strip():
            best = max(groups, key=lambda rg: self.title_similarity(album, rg.release_group_title))
            if self.title_similarity(album, best.release_group_title) >= _RG_TITLE_DISAMBIGUATION:
                return best
        return max(groups, key=self._rg_rank)

    async def _recording_match(self, target: TargetAlbum) -> MatchResult:
        if not target.track_title:
            return MatchResult(confidence=0.0)
        recordings = await self._mb_repo.search_recordings(target.artist, target.track_title)
        best_confidence = 0.0
        best: tuple["RecordingReleaseGroup", str] | None = None
        for rec in recordings:
            if not rec.release_groups:
                continue
            if not self._artist_floor_ok(target.artist, rec.artist):
                continue
            confidence = self.title_similarity(target.track_title, rec.title)
            if confidence < TEXT_MATCH_THRESHOLD or confidence <= best_confidence:
                continue
            rg = self._select_release_group(target.album, rec.release_groups)
            best_confidence = confidence
            best = (rg, rec.recording_mbid)
        if best is None:
            return MatchResult(confidence=0.0)
        rg, recording_mbid = best
        return MatchResult(
            confidence=round(best_confidence, 4),
            release_group_mbid=rg.release_group_mbid,
            release_mbid=rg.release_mbid,
            recording_mbid=recording_mbid,
        )

    async def resolve_recording_to_release_group(self, recording_id: str) -> str | None:
        """Tier 3: resolve an AcoustID recording MBID to a release-group MBID.

        (AUD-13) Delegates to ``MusicBrainzRepository`` - no raw HTTP, no second
        rate limiter. Fails open: any repo exception is logged and ``None`` is
        returned so the scanner falls through to manual review rather than dying.
        """
        if not recording_id:
            return None
        try:
            return await self._mb_repo.resolve_recording_to_release_group(recording_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Recording->release-group resolution failed for %s: %s", recording_id, exc
            )
            return None
