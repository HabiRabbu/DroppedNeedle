"""Wrong-album spec (shared, both sources).

Wraps ``names_different_album`` so a different album by the same artist ("Led
Zeppelin II" for a "Led Zeppelin" request) is rejected identically on both paths —
the rule can no longer drift between the scorers. Rejects on EXTRA album-name words
only and is gated on the artist being present, so an obfuscated release of the
requested album still passes (Q4). Lidarr ref: release-to-album match.
"""

from models.download import TargetAlbum

from services.native.title_match import names_different_album

from ..context import DecisionContext
from ..decision import Accept, Candidate, Decision, Disposition, Reject, RejectCode, SpecPolicy


def wrong_album(
    candidate: Candidate,
    target: TargetAlbum,
    context: DecisionContext,
    policy: SpecPolicy,
) -> Decision:
    if names_different_album(target.album_title, target.artist_name, candidate.match_text):
        return Reject(
            code=RejectCode.WRONG_ALBUM,
            detail=f"names a different album than {target.album_title!r}",
            disposition=Disposition.PERMANENT,
        )
    return Accept()
