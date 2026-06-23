"""T2.1 - Subsonic playlists CRUD via the bridged PlaylistService."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return env.client.get(f"/subsonic/rest/{endpoint}", params=q)


def _track_ids(env):
    res = _sub(_get(env, "search3", query=""))["searchResult3"]["song"]
    return [s["id"] for s in res]


async def test_create_get_update_delete_roundtrip(compat_env):
    songs = _track_ids(compat_env)
    # create with two songs
    created = _sub(_get(compat_env, "createPlaylist", name="My Mix",
                        songId=songs))["playlist"]
    pid = created["id"]
    assert pid.startswith("pl-")
    assert created["name"] == "My Mix"
    assert created["songCount"] == 2
    assert [e["id"] for e in created["entry"]] == songs  # songId<->file_id order

    # appears in getPlaylists (no entries)
    lists = _sub(_get(compat_env, "getPlaylists"))["playlists"]["playlist"]
    assert any(p["id"] == pid and p["songCount"] == 2 for p in lists)

    # getPlaylist returns entries
    got = _sub(_get(compat_env, "getPlaylist", id=pid))["playlist"]
    assert len(got["entry"]) == 2
    assert got["owner"] == "alice"

    # update: rename + remove index 0
    _sub(_get(compat_env, "updatePlaylist", playlistId=pid, name="Renamed",
              songIndexToRemove="0"))
    got2 = _sub(_get(compat_env, "getPlaylist", id=pid))["playlist"]
    assert got2["name"] == "Renamed"
    assert got2["songCount"] == 1
    assert got2["entry"][0]["id"] == songs[1]

    # update: add a song back
    _sub(_get(compat_env, "updatePlaylist", playlistId=pid, songIdToAdd=songs[0]))
    got3 = _sub(_get(compat_env, "getPlaylist", id=pid))["playlist"]
    assert got3["songCount"] == 2

    # delete
    _sub(_get(compat_env, "deletePlaylist", id=pid))
    after = _sub(_get(compat_env, "getPlaylists"))["playlists"].get("playlist", [])
    assert all(p["id"] != pid for p in after)


async def test_create_requires_name(compat_env):
    body = json.loads(_get(compat_env, "createPlaylist").content)["subsonic-response"]
    assert body["error"]["code"] == 10


async def test_create_replace_existing(compat_env):
    songs = _track_ids(compat_env)
    pid = _sub(_get(compat_env, "createPlaylist", name="Orig", songId=songs[0]))["playlist"]["id"]
    # replace contents via playlistId
    replaced = _sub(_get(compat_env, "createPlaylist", playlistId=pid, songId=songs[1]))["playlist"]
    assert replaced["songCount"] == 1
    assert replaced["entry"][0]["id"] == songs[1]


async def test_get_unknown_playlist_is_70(compat_env):
    body = json.loads(_get(compat_env, "getPlaylist", id="pl-nope").content)["subsonic-response"]
    assert body["error"]["code"] == 70


async def test_library_file_id_roundtrip_to_stream(compat_env):
    # songId (tr-file) -> createPlaylist -> getPlaylist entry id decodes back to the
    # same tr-file (Q11 library_file_id linkage)
    songs = _track_ids(compat_env)
    pid = _sub(_get(compat_env, "createPlaylist", name="X", songId=songs[0]))["playlist"]["id"]
    entry = _sub(_get(compat_env, "getPlaylist", id=pid))["playlist"]["entry"][0]
    assert entry["id"] == songs[0]
    # and the persisted row carries library_file_id
    tracks = await compat_env.playlists.get_tracks(pid[3:])
    assert tracks[0].library_file_id == songs[0][3:]
    assert tracks[0].source_type == "droppedneedle-local"
