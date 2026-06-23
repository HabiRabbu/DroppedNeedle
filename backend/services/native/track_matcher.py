"""Per-track matcher.

Single-track scoring with no group/coherence phase: scores each candidate file
against the target track and wraps the best as a one-file ``ScoredCandidate`` so
the orchestrator's track branch and the Review tab consume it identically to an
album candidate. Reuses the album scorer's ``_file_confidence`` and the shared
quarantine + quality-tier filters (codec/tier gate + absolute highest-tier
preference).
"""

from infrastructure.persistence.download_store import DownloadStore
from models.download import ScoredCandidate, TargetTrack
from repositories.protocols.download_client import DownloadSearchResult
from services.native.album_preflight_scorer import _file_confidence
from services.native.quality_tiers import (
    DEFAULT_QUALITY_MAX,
    DEFAULT_QUALITY_MIN,
    file_tier,
    in_range,
    is_flac_or_mp3,
    tier_rank,
)


class TrackMatcher:
    def __init__(
        self,
        download_store: DownloadStore,
        *,
        quality_min: str = DEFAULT_QUALITY_MIN,
        quality_max: str = DEFAULT_QUALITY_MAX,
        flac_mp3_only: bool = True,
    ):
        self._store = download_store
        self._quality_min = quality_min
        self._quality_max = quality_max
        self._flac_mp3_only = flac_mp3_only

    async def match(
        self,
        target: TargetTrack,
        results: list[DownloadSearchResult],
        *,
        auto_accept_threshold: float = 0.70,
        manual_threshold: float = 0.50,
    ) -> ScoredCandidate | None:
        quarantined = await self._store.load_quarantine_set()
        filtered = [r for r in results if (r.username, r.filename) not in quarantined]
        if self._flac_mp3_only:
            filtered = [r for r in filtered if is_flac_or_mp3(r)]
        filtered = [
            r
            for r in filtered
            if in_range(file_tier(r), self._quality_min, self._quality_max)
        ]
        if not filtered:
            return None

        best: DownloadSearchResult | None = None
        best_key: tuple[int, float] | None = None
        best_score = -1.0
        for file in filtered:
            score = _file_confidence(
                target.track_title, target.artist_name, target.duration_seconds, file
            )
            # prefer the higher tier, then better match
            key = (tier_rank(file_tier(file)), score)
            if best_key is None or key > best_key:
                best_key = key
                best = file
                best_score = score

        if best is None:
            return None

        if best_score >= auto_accept_threshold:
            tier = "auto"
        elif best_score >= manual_threshold:
            tier = "manual"
        else:
            tier = "rejected"

        return ScoredCandidate(
            username=best.username,
            parent_directory=best.parent_directory,
            files=[best],
            coherence=best_score,
            file_confidence=best_score,
            final_score=best_score,
            tier=tier,
        )
