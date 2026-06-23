"""T2.2 - Subsonic star/unstar/getStarred2 + setRating no-op."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return env.client.get(f"/subsonic/rest/{endpoint}", params=q)


def _first_ids(env):
    res = _sub(_get(env, "search3", query=""))["searchResult3"]
    return res["song"][0]["id"], res["album"][0]["id"], res["artist"][0]["id"]


async def test_star_song_then_get_starred2(compat_env):
    song_id, _, _ = _first_ids(compat_env)
    _sub(_get(compat_env, "star", id=song_id))
    starred = _sub(_get(compat_env, "getStarred2"))["starred2"]
    songs = starred.get("song", [])
    assert any(s["id"] == song_id for s in songs)
    assert all("starred" in s for s in songs)  # ISO timestamp present


async def test_star_album_and_artist(compat_env):
    _, album_id, artist_id = _first_ids(compat_env)
    _sub(_get(compat_env, "star", albumId=album_id, artistId=artist_id))
    starred = _sub(_get(compat_env, "getStarred2"))["starred2"]
    assert any(a["id"] == album_id for a in starred.get("album", []))
    assert any(a["id"] == artist_id for a in starred.get("artist", []))


async def test_unstar_removes(compat_env):
    song_id, _, _ = _first_ids(compat_env)
    _sub(_get(compat_env, "star", id=song_id))
    _sub(_get(compat_env, "unstar", id=song_id))
    starred = _sub(_get(compat_env, "getStarred2"))["starred2"]
    assert all(s["id"] != song_id for s in starred.get("song", []))


async def test_star_id_routes_by_prefix(compat_env):
    # star an album via the generic `id` param (prefix al-) - routed correctly
    _, album_id, _ = _first_ids(compat_env)
    _sub(_get(compat_env, "star", id=album_id))
    starred = _sub(_get(compat_env, "getStarred2"))["starred2"]
    assert any(a["id"] == album_id for a in starred.get("album", []))


async def test_get_starred_file_structure(compat_env):
    song_id, album_id, _ = _first_ids(compat_env)
    _sub(_get(compat_env, "star", id=song_id, albumId=album_id))
    starred = _sub(_get(compat_env, "getStarred"))["starred"]
    assert starred["album"][0]["isDir"] is True
    assert starred["song"][0]["isDir"] is False


async def test_set_rating_is_accepted_noop(compat_env):
    song_id, _, _ = _first_ids(compat_env)
    body = _sub(_get(compat_env, "setRating", id=song_id, rating="5"))
    assert body["status"] == "ok"
    # nothing persisted - song still has no rating surfaced; just assert it didn't error
    song = _sub(_get(compat_env, "getSong", id=song_id))["song"]
    assert "userRating" not in song
