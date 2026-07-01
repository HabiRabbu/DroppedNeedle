"""Ignored / required terms specs (shared, both sources).

User-tunable release filtering on top of the always-on identity guards. Each term is a
plain case-insensitive substring, or a ``/regex/`` when wrapped in slashes (matched
case-insensitively) — mirroring Lidarr's Release Profile terms. Both default to empty
(no-op) so an unconfigured install is unchanged.

- ``ignored_terms``: drop any candidate whose name matches ANY term.
- ``required_terms``: when non-empty, keep only candidates matching AT LEAST ONE.
"""

import re

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy


def _term_matches(text: str, term: str) -> bool:
    if len(term) >= 2 and term.startswith("/") and term.endswith("/"):
        try:
            return bool(re.search(term[1:-1], text, re.IGNORECASE))
        except re.error:
            return False  # a malformed /regex/ never matches (and never crashes scoring)
    return term.lower() in text.lower()


def ignored_terms(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    text = candidate.match_text or ""
    for term in policy.ignored_terms:
        if term and _term_matches(text, term):
            return Reject(
                code=RejectCode.IGNORED_TERM,
                detail=f"matched ignored term {term!r}",
                disposition=Disposition.PERMANENT,
            )
    return Accept()


def required_terms(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    terms = [t for t in policy.required_terms if t]
    if not terms:
        return Accept()
    text = candidate.match_text or ""
    if any(_term_matches(text, t) for t in terms):
        return Accept()
    return Reject(
        code=RejectCode.REQUIRED_TERM_MISSING,
        detail="matched none of the required terms",
        disposition=Disposition.PERMANENT,
    )
