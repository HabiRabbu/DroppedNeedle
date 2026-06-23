"""MusicBrainzIdResolver — resolve a release MBID to its release-group MBID.

Used when a file's tags carry ``MusicBrainz Album Id`` (the specific release)
but not ``MusicBrainz Release Group Id`` (the album-grouping key the library
uses). Delegates to the existing, rate-limited ``MusicBrainzRepository`` method
(AUD-13 — no raw HTTP here).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repositories.musicbrainz_repository import MusicBrainzRepository


class MusicBrainzIdResolver:
    def __init__(self, mb_repo: "MusicBrainzRepository") -> None:
        self._mb_repo = mb_repo

    async def resolve_release_to_release_group(self, release_mbid: str) -> str | None:
        if not release_mbid:
            return None
        return await self._mb_repo.get_release_group_id_from_release(release_mbid)
