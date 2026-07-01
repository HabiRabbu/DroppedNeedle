"""Quality-range spec (shared, both sources).

The candidate's tier must lie within ``[quality_min, quality_max]``. An ``unknown``
tier — Usenet's noisy/obfuscated titles where the codec can't be read — PASSES, the
import tag-match being the real quality truth (D10). Soulseek never yields
``unknown`` (every file has a determinable tier), so the gate is exact there.
Replaces the duplicated ``in_range`` check. Lidarr ref: ``QualityAllowedByProfile``.
"""

from models.download import TargetAlbum

from services.native.quality_tiers import in_range

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy


def quality_range(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if candidate.tier == "unknown":
        return Accept()
    if in_range(candidate.tier, policy.quality_min, policy.quality_max):
        return Accept()
    return Reject(
        code=RejectCode.QUALITY_REJECTED,
        detail=f"tier {candidate.tier!r} outside [{policy.quality_min}, {policy.quality_max}]",
        disposition=Disposition.PERMANENT,
    )
