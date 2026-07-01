"""Retention spec (Usenet).

Reject a release older than the provider's retention window: beyond it the articles
can't be fetched, so the download would only partially complete and fail. ``0`` days =
no limit (safe-off default). Soulseek candidates carry ``usenet_date=None`` and pass.
Lidarr ref: ``RetentionSpecification``.
"""

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy

_DAY = 86400.0


def retention(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if policy.usenet_retention_days <= 0 or candidate.usenet_date is None or not context.now:
        return Accept()
    age_days = (context.now - candidate.usenet_date) / _DAY
    if age_days > policy.usenet_retention_days:
        return Reject(
            code=RejectCode.RETENTION_EXCEEDED,
            detail=f"{age_days:.0f}d old exceeds {policy.usenet_retention_days}d retention",
            disposition=Disposition.PERMANENT,
        )
    return Accept()
