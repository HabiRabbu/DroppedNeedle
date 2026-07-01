"""Minimum-age / propagation spec (Usenet, grab-time).

Skip a release younger than the configured age so it can finish propagating across
Usenet servers before we grab it (a too-young NZB downloads only partially and fails).
The rejection is ``TEMPORARY`` — the release becomes eligible once it has aged, so a
future auto-retry/search picks it up rather than blocklisting it.

``usenet_min_age_minutes == 0`` = off (Lidarr's MinimumAge default). This is a DISTINCT
knob from ``DownloadPolicySettings.usenet_min_release_age_minutes`` (the post-fail
"don't blocklist a too-young release" leniency), which is left untouched. Soulseek
candidates carry ``usenet_date=None`` and pass.
"""

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy

_MINUTE = 60.0


def min_age(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if policy.usenet_min_age_minutes <= 0 or candidate.usenet_date is None or not context.now:
        return Accept()
    age_minutes = (context.now - candidate.usenet_date) / _MINUTE
    if age_minutes < policy.usenet_min_age_minutes:
        return Reject(
            code=RejectCode.TOO_YOUNG,
            detail=f"{age_minutes:.0f}m old is under the {policy.usenet_min_age_minutes}m floor",
            disposition=Disposition.TEMPORARY,
        )
    return Accept()
