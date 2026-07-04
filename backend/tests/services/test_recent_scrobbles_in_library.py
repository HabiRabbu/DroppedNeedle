"""Recently Scrobbled: an owned album must read as in_library even though its raw
Last.fm RELEASE mbid differs from the library's RELEASE-GROUP mbid (the resolved rg is
what library_mbids is keyed by, so in_library must be recomputed after resolution)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.home import HomeAlbum
from services.discover.homepage_service import DiscoverHomepageService


def _svc() -> DiscoverHomepageService:
    svc = DiscoverHomepageService.__new__(DiscoverHomepageService)
    svc._transformers = MagicMock()
    # the transformer sets in_library against the RAW release mbid (misses the library,
    # which is keyed by release-group mbid) - this is the bug source we recompute past
    svc._transformers.lastfm_recent_to_home = lambda track, lib: HomeAlbum(
        mbid=track.album_mbid,
        name=track.album_name,
        artist_name=track.artist_name,
        in_library=False,
        source="lastfm",
    )
    svc._mb_repo = MagicMock()
    return svc


def _track(album_mbid: str, album_name: str = "Owned Album", artist: str = "Artist"):
    return SimpleNamespace(album_mbid=album_mbid, album_name=album_name, artist_name=artist)


@pytest.mark.asyncio
async def test_owned_album_is_in_library_after_rg_resolution():
    svc = _svc()
    # release "rel-1" resolves to release-group "rg-owned", which IS in the library
    svc._mb_repo.get_release_group_id_from_release = AsyncMock(return_value="rg-owned")

    section = await svc._build_lastfm_recent_scrobbles(
        {"lfm_recent": [_track("rel-1")]}, {"rg-owned"}
    )

    assert section is not None
    assert section.items[0].mbid == "rg-owned"
    assert section.items[0].in_library is True


@pytest.mark.asyncio
async def test_unowned_album_stays_out_of_library():
    svc = _svc()
    svc._mb_repo.get_release_group_id_from_release = AsyncMock(return_value="rg-other")

    section = await svc._build_lastfm_recent_scrobbles(
        {"lfm_recent": [_track("rel-2")]}, {"rg-owned"}
    )

    assert section is not None
    assert section.items[0].in_library is False
