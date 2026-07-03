"""PreviewRepository: Deezer-primary/iTunes-fallback 30s previews.

Wire shapes below mirror live responses captured 2026-07-03 (see deezer_models
docstring). No network: a fake httpx client returns canned httpx.Response objects.
"""

import httpx
import pytest

from repositories.preview_repository import PreviewRepository

DEEZER_TRACK_HIT = b'''{"data":[{"id":398570642,"title":"Bitter Sweet Symphony (Remastered 2016)",
"title_short":"Bitter Sweet Symphony","duration":357,
"preview":"https://cdnt-preview.dzcdn.net/api/1/x.mp3?hdnea=exp=1",
"artist":{"id":869,"name":"The Verve"}}]}'''

DEEZER_EMPTY = b'{"data":[]}'

DEEZER_ALBUM_HIT = b'{"data":[{"id":302127,"title":"Urban Hymns","artist":{"id":869,"name":"The Verve"}}]}'

DEEZER_ALBUM_TRACKS = b'''{"data":[
{"id":1,"title":"Bitter Sweet Symphony","title_short":"Bitter Sweet Symphony","duration":357,"track_position":1,"preview":"https://p/1.mp3"},
{"id":2,"title":"Sonnet","title_short":"Sonnet","duration":261,"track_position":2,"preview":"https://p/2.mp3"},
{"id":3,"title":"No Preview","title_short":"No Preview","duration":100,"track_position":3,"preview":""},
{"id":4,"title":"The Rolling People","title_short":"The Rolling People","duration":421,"track_position":4,"preview":"https://p/4.mp3"}
]}'''

ITUNES_COVER_FIRST = b'''{"resultCount":2,"results":[
{"artistName":"David Garrett","trackName":"Bitter Sweet Symphony","collectionName":"Rock Revolution","previewUrl":"https://itunes/cover.m4a"},
{"artistName":"The Verve","trackName":"Bitter Sweet Symphony","collectionName":"Urban Hymns","previewUrl":"https://itunes/real.m4a"}
]}'''


class FakeClient:
    """Routes URLs to canned responses; records requests."""

    def __init__(self, routes: dict[str, bytes | int]):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, params=None, timeout=None):
        self.calls.append(url)
        for fragment, payload in self.routes.items():
            if fragment in url:
                if isinstance(payload, int):
                    return httpx.Response(payload, request=httpx.Request("GET", url))
                return httpx.Response(200, content=payload, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))


class TestTrackPreview:
    @pytest.mark.asyncio
    async def test_deezer_hit_wins(self):
        repo = PreviewRepository(FakeClient({"api.deezer.com/search": DEEZER_TRACK_HIT}))
        found, provider = await repo.get_track_preview("The Verve", "Bitter Sweet Symphony")
        assert provider == "deezer"
        assert found is not None
        assert found.preview_url.startswith("https://cdnt-preview")
        assert found.title == "Bitter Sweet Symphony"

    @pytest.mark.asyncio
    async def test_falls_back_to_itunes_and_skips_covers(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search": DEEZER_EMPTY,
                    "itunes.apple.com": ITUNES_COVER_FIRST,
                }
            )
        )
        found, provider = await repo.get_track_preview("The Verve", "Bitter Sweet Symphony")
        assert provider == "itunes"
        assert found is not None
        # the David Garrett cover (top hit) must be rejected on artist mismatch
        assert found.preview_url == "https://itunes/real.m4a"
        assert found.artist_name == "The Verve"

    @pytest.mark.asyncio
    async def test_returns_none_when_both_providers_empty(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search": DEEZER_EMPTY,
                    "itunes.apple.com": b'{"resultCount":0,"results":[]}',
                }
            )
        )
        found, provider = await repo.get_track_preview("Nobody", "Nothing")
        assert found is None
        assert provider is None

    @pytest.mark.asyncio
    async def test_deezer_http_error_degrades_to_itunes(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search": 500,
                    "itunes.apple.com": ITUNES_COVER_FIRST,
                }
            )
        )
        found, provider = await repo.get_track_preview("The Verve", "Bitter Sweet Symphony")
        assert provider == "itunes"
        assert found is not None


class TestAlbumPreview:
    @pytest.mark.asyncio
    async def test_deezer_album_sampler_ordered_and_skips_previewless(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search/album": DEEZER_ALBUM_HIT,
                    "api.deezer.com/album/302127/tracks": DEEZER_ALBUM_TRACKS,
                }
            )
        )
        tracks, provider = await repo.get_album_preview_tracks("The Verve", "Urban Hymns", limit=4)
        assert provider == "deezer"
        assert [t.position for t in tracks] == [1, 2, 4]  # previewless track 3 skipped
        assert all(t.preview_url for t in tracks)

    @pytest.mark.asyncio
    async def test_limit_caps_sampler_length(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search/album": DEEZER_ALBUM_HIT,
                    "api.deezer.com/album/302127/tracks": DEEZER_ALBUM_TRACKS,
                }
            )
        )
        tracks, _ = await repo.get_album_preview_tracks("The Verve", "Urban Hymns", limit=2)
        assert len(tracks) == 2

    @pytest.mark.asyncio
    async def test_no_album_match_returns_empty(self):
        repo = PreviewRepository(
            FakeClient(
                {
                    "api.deezer.com/search/album": DEEZER_EMPTY,
                    "itunes.apple.com": b'{"resultCount":0,"results":[]}',
                }
            )
        )
        tracks, provider = await repo.get_album_preview_tracks("X", "Y")
        assert tracks == []
        assert provider is None
