"""T1.3 - Subsonic system + browsing endpoints against a seeded library."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return _sub(env.client.get(f"/subsonic/rest/{endpoint}", params=q))


async def test_get_license(compat_env):
    body = _get(compat_env, "getLicense")
    assert body["license"]["valid"] is True


async def test_get_music_folders(compat_env):
    body = _get(compat_env, "getMusicFolders")
    folders = body["musicFolders"]["musicFolder"]
    assert folders == [{"id": 1, "name": "DroppedNeedle"}]


async def test_get_artists_index_shape(compat_env):
    body = _get(compat_env, "getArtists")
    artists = body["artists"]
    assert artists["ignoredArticles"]
    # Radiohead -> index "R"
    letters = {idx["name"] for idx in artists["index"]}
    assert "R" in letters
    r = next(idx for idx in artists["index"] if idx["name"] == "R")
    assert isinstance(r["artist"], list)
    a = r["artist"][0]
    assert a["name"] == "Radiohead"
    assert a["id"].startswith("ar-")


async def test_get_artist_then_album_then_song_drilldown(compat_env):
    artists = _get(compat_env, "getArtists")["artists"]
    artist_id = artists["index"][0]["artist"][0]["id"]

    artist = _get(compat_env, "getArtist", id=artist_id)["artist"]
    assert isinstance(artist["album"], list) and artist["album"]
    album_id = artist["album"][0]["id"]
    assert album_id.startswith("al-")

    album = _get(compat_env, "getAlbum", id=album_id)["album"]
    songs = album["song"]
    assert len(songs) == 2
    # ordered by disc/track
    assert [s["track"] for s in songs] == [1, 2]
    s0 = songs[0]
    assert s0["id"].startswith("tr-")
    # OpenSubsonic-required song fields
    assert s0["mediaType"] == "song"
    assert s0["channelCount"] == 2
    assert s0["samplingRate"] == 44100
    assert s0["contentType"] == "audio/flac"

    song = _get(compat_env, "getSong", id=s0["id"])["song"]
    assert song["title"] == "Airbag"


async def test_get_album_list2_newest(compat_env):
    body = _get(compat_env, "getAlbumList2", type="newest")
    albums = body["albumList2"]["album"]
    assert len(albums) == 1
    assert albums[0]["name"] == "OK Computer"
    assert albums[0]["id"].startswith("al-")


async def test_get_album_list2_requires_type(compat_env):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret}
    body = json.loads(compat_env.client.get("/subsonic/rest/getAlbumList2", params=q).content)
    assert body["subsonic-response"]["error"]["code"] == 10


async def test_get_album_list_file_structure(compat_env):
    body = _get(compat_env, "getAlbumList", type="alphabeticalByName")
    album = body["albumList"]["album"][0]
    assert album["isDir"] is True
    assert album["id"].startswith("al-")


async def test_get_random_songs(compat_env):
    body = _get(compat_env, "getRandomSongs", size="10")
    songs = body["randomSongs"]["song"]
    assert {s["title"] for s in songs} == {"Airbag", "Paranoid Android"}


async def test_get_indexes_file_structure(compat_env):
    body = _get(compat_env, "getIndexes")
    idx = body["indexes"]
    assert idx["index"][0]["artist"][0]["name"] == "Radiohead"


async def test_get_music_directory_artist_then_album(compat_env):
    artist_id = _get(compat_env, "getArtists")["artists"]["index"][0]["artist"][0]["id"]
    d = _get(compat_env, "getMusicDirectory", id=artist_id)["directory"]
    assert d["child"][0]["isDir"] is True
    album_id = d["child"][0]["id"]
    d2 = _get(compat_env, "getMusicDirectory", id=album_id)["directory"]
    assert len(d2["child"]) == 2
    assert d2["child"][0]["isDir"] is False


async def test_unknown_album_id_is_70(compat_env):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret,
         "id": "al-does-not-exist"}
    body = json.loads(compat_env.client.get("/subsonic/rest/getAlbum", params=q).content)
    assert body["subsonic-response"]["error"]["code"] == 70


async def test_xml_format_drilldown(compat_env):
    q = {"v": "1.16.1", "c": "pytest", "f": "xml", "apiKey": compat_env.secret}
    r = compat_env.client.get("/subsonic/rest/getArtists", params=q)
    assert r.headers["content-type"].startswith("application/xml")
    assert b'<artists' in r.content and b'name="Radiohead"' in r.content
