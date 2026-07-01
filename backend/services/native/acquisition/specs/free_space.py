"""Free-space spec (shared, both sources).

Reject a candidate that wouldn't fit on the download destination (its size, plus a
safety margin, exceeds the free bytes ``build_context`` measured). ``context.free_bytes
is None`` means the disk is unknown — the spec then passes. Disposition is
``LOCAL_FAULT``: it's our disk, never the source's fault, so it must not blocklist a peer
or release. Lidarr ref: ``FreeSpaceSpecification``.

NOTE: the relevant disk is the download CLIENT's destination dir, which the scorers don't
know yet (staging is metadata-only). Until the source strategy supplies it (step 4),
``free_bytes`` stays ``None`` at the scorer call sites and this spec is a no-op there; the
logic and its unit tests are in place for that wiring.
"""

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy

_MIN_FREE_MARGIN = 100 * 1024 * 1024  # keep 100MB headroom on the destination


def free_space(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if context.free_bytes is None:
        return Accept()
    if context.free_bytes - candidate.size_bytes < _MIN_FREE_MARGIN:
        return Reject(
            code=RejectCode.INSUFFICIENT_SPACE,
            detail=f"{context.free_bytes // (1024 * 1024)}MB free can't hold the candidate",
            disposition=Disposition.LOCAL_FAULT,
        )
    return Accept()
