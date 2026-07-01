"""Maximum-size spec (shared, both sources).

Hard upper bound on a single album's total bytes — rejects a mislabeled
boxset/discography before the bytes are spent. ``max_size_mb == 0`` means unbounded
(safe-off default), so an unconfigured install is unchanged. Lidarr ref: ``MaximumSize``.

(File-count-based boxset detection is intentionally deferred: named boxsets/discographies
are already caught by ``wrong_edition``, and there is no file-count config to drive a
numeric threshold without guessing.)
"""

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy

_MB = 1024 * 1024


def max_size(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if policy.max_size_mb <= 0 or not candidate.size_bytes:
        return Accept()
    limit = policy.max_size_mb * _MB
    if candidate.size_bytes > limit:
        return Reject(
            code=RejectCode.MAX_SIZE_EXCEEDED,
            detail=f"{candidate.size_bytes // _MB}MB exceeds the {policy.max_size_mb}MB cap",
            disposition=Disposition.PERMANENT,
        )
    return Accept()
