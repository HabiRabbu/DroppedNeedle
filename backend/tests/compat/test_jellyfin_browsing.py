"""T4.3 - Jellyfin browsing: both dialects, drill-down, ArtistIds union (Q23)."""

import json
from pathlib import Path

import pytest

from models.audio import AudioInfo, AudioTag
from services.native.library_manager import _synth_artist_mbid

pytestmark = pytest.mark.asyncio


def _h(env):
    return {"Authorization": f'MediaBrowser Token="{env.secret}", Client="pytest"'}


def _jget(env, path, **params):
    r = env.client.get(f"/jellyfin{path}", params=params, headers=_h(env))
    assert r.status_code == 200, r.content
    return json.loads(r.content)


async def test_views_both_dialects(compat_env):
    legacy = _jget(compat_env, "/Users/user-alice/Views")
    modern = _jget(compat_env, "/UserViews")
    for body in (legacy, modern):
        assert body["TotalRecordCount"] == 1
        view = body["Items"][0]
        assert view["Type"] == "CollectionFolder"
        assert view["CollectionType"] == "music"
        # real-server fields strict clients (Manet) require to accept the music library
        assert view["LocationType"] == "FileSystem"
        assert view["ImageTags"].get("Primary")  # non-empty
        assert view["UserData"]["ItemId"] == view["Id"]
        assert view["SortName"] == "Music"  # Manet's strict Codable requires SortName
    assert legacy["Items"][0]["Id"] == modern["Items"][0]["Id"]  # stable id


async def test_library_view_primary_image_resolves(compat_env):
    # The view advertises ImageTags.Primary, so the image fetch must serve bytes, not 404.
    lib_id = _jget(compat_env, "/UserViews")["Items"][0]["Id"]
    r = compat_env.client.get(f"/jellyfin/Items/{lib_id}/Images/Primary")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_items_both_dialects_albums(compat_env):
    legacy = _jget(compat_env, "/Users/user-alice/Items", IncludeItemTypes="MusicAlbum")
    modern = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum")
    assert legacy["Items"] and modern["Items"]
    assert legacy["Items"][0]["Name"] == modern["Items"][0]["Name"] == "OK Computer"
    assert modern["Items"][0]["Type"] == "MusicAlbum"
    assert modern["Items"][0]["SortName"]  # every item carries SortName (strict clients)


async def test_drilldown_artist_album_track(compat_env):
    artists = _jget(compat_env, "/Artists/AlbumArtists")["Items"]
    artist = next(a for a in artists if a["Name"] == "Radiohead")
    assert artist["Type"] == "MusicArtist"

    albums = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum",
                   AlbumArtistIds=artist["Id"], Recursive="true")["Items"]
    assert albums and albums[0]["Name"] == "OK Computer"
    album_id = albums[0]["Id"]

    tracks = _jget(compat_env, "/Items", ParentId=album_id)["Items"]
    assert len(tracks) == 2
    assert tracks[0]["Type"] == "Audio"
    assert tracks[0]["RunTimeTicks"] > 0
    assert [t["IndexNumber"] for t in tracks] == [1, 2]


async def test_browse_query_params_are_case_insensitive(compat_env):
    # Real Jellyfin clients (Jellify et al.) send camelCase params - parentId,
    # includeItemTypes, limit - because the production ASP.NET Core server binds query
    # strings case-insensitively. Regression for the album-drill returning all albums and
    # the "Tracks tab shows Albums" bug (params were read PascalCase-only and silently lost).
    audio = _jget(compat_env, "/Items", includeItemTypes="Audio")["Items"]
    assert audio and all(i["Type"] == "Audio" for i in audio)

    album_id = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]["Id"]
    tracks = _jget(compat_env, "/Items", parentId=album_id)["Items"]
    assert len(tracks) == 2
    assert all(t["Type"] == "Audio" for t in tracks)


async def test_items_filters_returns_genres_not_404(compat_env):
    # Manet calls /Items/Filters before listing; it must not be captured by
    # /Items/{item_id} (404). Both dialects return QueryFilters with the genre facet.
    for path in ("/Items/Filters", "/Users/user-alice/Items/Filters"):
        body = _jget(compat_env, path, IncludeItemTypes="Audio")
        assert "Genres" in body and isinstance(body["Genres"], list)
        assert "Alternative Rock" in body["Genres"]
    # a real album id still resolves through the single-item route
    album_id = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]["Id"]
    assert _jget(compat_env, f"/Items/{album_id}")["Type"] == "MusicAlbum"


async def test_items_carry_jellyfin_always_present_fields(compat_env):
    # Fields real Jellyfin sets unconditionally on every item (DtoService.AttachBasicFields)
    # + SortName (requested via Fields). Strict Swift clients (Manet) require them and fail
    # decoding if any is absent. Verify on a track and an album.
    album = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]
    track = _jget(compat_env, "/Items", ParentId=album["Id"])["Items"][0]
    for item in (album, track):
        for key in ("Id", "Name", "Type", "ServerId", "MediaType", "IsFolder",
                    "SortName", "ImageTags", "ImageBlurHashes", "LocationType",
                    "Genres", "DateCreated", "Artists", "ArtistItems", "AlbumArtists"):
            assert key in item, f"{item['Type']} missing {key}"
        assert item["LocationType"] == "FileSystem"


async def test_music_item_artist_and_genre_fields_never_null():
    # Manet requires Genres/DateCreated/ArtistItems even when the underlying row is sparse;
    # build an album with no genre/artist/date and confirm they serialise as [] / a date, not null.
    from api.compat.jellyfin.builders import JellyfinBuilder
    from services.compat.view_models import ViewAlbum

    class _Ids:
        async def to_jf(self, kind, internal):
            return "x" * 32

    class _Cover:
        async def get_release_group_cover_etag(self, *a, **k):
            return None

    b = JellyfinBuilder(_Ids(), _Cover(), "srv")
    album = await b.album(ViewAlbum(rg_mbid="rg", title="Untagged"))  # everything else null
    assert album.Genres == [] and album.ArtistItems == [] and album.Artists == []
    assert album.AlbumArtists == [] and album.DateCreated is not None
    # Manet rejects whole-second ISO; dates must be .NET round-trip (7 fractional digits + Z)
    import re
    dated = await b.album(ViewAlbum(rg_mbid="rg2", title="Dated", date_added=1_700_000_000))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z", dated.DateCreated)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z", album.DateCreated)


async def test_single_item_both_dialects(compat_env):
    album_id = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]["Id"]
    legacy = _jget(compat_env, f"/Users/user-alice/Items/{album_id}")
    modern = _jget(compat_env, f"/Items/{album_id}")
    assert legacy["Name"] == modern["Name"] == "OK Computer"


async def test_unknown_item_404(compat_env):
    r = compat_env.client.get(
        "/jellyfin/Items/00000000000000000000000000000000", headers=_h(compat_env)
    )
    assert r.status_code == 404


async def test_genres(compat_env):
    genres = _jget(compat_env, "/Genres")["Items"]
    assert any(g["Name"] == "Alternative Rock" and g["Type"] == "MusicGenre" for g in genres)
    # /MusicGenres dialect
    assert _jget(compat_env, "/MusicGenres")["Items"]


async def test_search_term(compat_env):
    res = _jget(compat_env, "/Items", IncludeItemTypes="MusicAlbum", SearchTerm="OK Comp")
    assert any(a["Name"] == "OK Computer" for a in res["Items"])


async def test_paging_total_record_count(compat_env):
    res = _jget(compat_env, "/Items", IncludeItemTypes="Audio", StartIndex="0", Limit="1")
    assert res["TotalRecordCount"] == 2
    assert len(res["Items"]) == 1
    assert res["StartIndex"] == 0


async def test_artistids_union_vs_albumartistids_strict(compat_env):
    # a featured-artist track: track artist != album artist (Q23)
    await compat_env.lm.upsert_file(
        Path("/music/feat.flac"),
        AudioTag(title="Feat Track", artist="Featured Guy", album="Collab",
                 track_number=1, album_artist="Main Band", year=2020),
        AudioInfo(duration_seconds=180.0, bitrate=900, sample_rate=44100, channels=2,
                  file_format="flac", file_size_bytes=1000, bit_depth=16),
        release_group_mbid="rg-collab-0000000000000000000000", recording_mbid="rec-feat",
        file_mtime=1.0,
    )
    feat_jf = await compat_env.id_map.to_jf("artist", _synth_artist_mbid("Featured Guy"))
    main_jf = await compat_env.id_map.to_jf("artist", _synth_artist_mbid("Main Band"))

    def _titles(**params):
        return {t["Name"] for t in _jget(compat_env, "/Items", IncludeItemTypes="Audio", **params)["Items"]}

    # ArtistIds (union): both the featured and the album artist match
    assert "Feat Track" in _titles(ArtistIds=feat_jf)
    assert "Feat Track" in _titles(ArtistIds=main_jf)
    # AlbumArtistIds (strict): only the album artist matches
    assert "Feat Track" in _titles(AlbumArtistIds=main_jf)
    assert "Feat Track" not in _titles(AlbumArtistIds=feat_jf)
