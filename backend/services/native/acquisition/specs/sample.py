"""Sample spec (shared, both sources).

Reject a release/folder marked as a "sample" (a teaser clip, not the album). Lidarr
ref: ``NotSample``. Conservative to avoid false positives: matches the standalone word
``sample`` only (not ``sampler``/``samples``), strips the ``sample rate`` quality
descriptor first, and is gated on the request — if the user genuinely asked for an
album whose title contains "sample", it's kept. The tiny-fragment case is separately
handled by the Usenet size-plausibility check.
"""

import re

from models.download import TargetAlbum

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy

_SAMPLE_RE = re.compile(r"\bsample\b", re.IGNORECASE)
_SAMPLE_RATE_RE = re.compile(r"\bsample[\s\-]?rate\b", re.IGNORECASE)


def sample(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    text = _SAMPLE_RATE_RE.sub(" ", (candidate.match_text or "").replace("_", " "))
    if not _SAMPLE_RE.search(text):
        return Accept()
    if _SAMPLE_RE.search(target.album_title or ""):
        return Accept()  # the requested album genuinely contains "sample"
    return Reject(
        code=RejectCode.SAMPLE,
        detail="release looks like a sample, not the full album",
        disposition=Disposition.PERMANENT,
    )
