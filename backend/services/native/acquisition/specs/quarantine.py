"""Quarantine / blocklist spec (shared, both sources).

A pure membership test against the snapshot ``build_context`` took — no I/O.
Replaces the duplicated inline ``load_quarantine_set`` + ``(source, identity) in
set`` check that lived in both scorers (de-drift). Lidarr ref: ``BlocklistSpecification``.
"""

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy


def quarantine(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if candidate.identity and (candidate.source, candidate.identity) in context.quarantine_set:
        return Reject(
            code=RejectCode.BLOCKLISTED,
            detail=f"{candidate.source} identity is quarantined",
            disposition=Disposition.PERMANENT,
        )
    return Accept()
