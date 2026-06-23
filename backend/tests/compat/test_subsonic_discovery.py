"""T2.4 - Subsonic getTopSongs / getSimilarSongs2 (owned-local, no outbound)."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return env.client.get(f"/subsonic/rest/{endpoint}", params=q)


async def test_get_top_songs_after_scrobble(compat_env):
    song = _sub(_get(compat_env, "search3", query=""))["searchResult3"]["song"][0]
    _sub(_get(compat_env, "scrobble", id=song["id"], submission="true"))
    top = _sub(_get(compat_env, "getTopSongs", artist="Radiohead"))["topSongs"]["song"]
    # owned + active tracks by the artist, most-played first
    assert top[0]["id"] == song["id"]
    assert all(s["artist"] == "Radiohead" for s in top)


async def test_get_top_songs_requires_artist(compat_env):
    body = json.loads(_get(compat_env, "getTopSongs").content)["subsonic-response"]
    assert body["error"]["code"] == 10


async def test_get_similar_songs2_same_artist_local_only(compat_env):
    artist_id = _sub(_get(compat_env, "getArtists"))["artists"]["index"][0]["artist"][0]["id"]
    res = _sub(_get(compat_env, "getSimilarSongs2", id=artist_id))["similarSongs2"]
    titles = {s["title"] for s in res["song"]}
    # local-only default -> same-artist pool only, intersected with owned library
    assert titles == {"Airbag", "Paranoid Android"}


async def test_get_similar_songs_file_structure(compat_env):
    artist_id = _sub(_get(compat_env, "getArtists"))["artists"]["index"][0]["artist"][0]["id"]
    res = _sub(_get(compat_env, "getSimilarSongs", id=artist_id))["similarSongs"]
    assert len(res["song"]) == 2


async def test_similar_songs_unknown_artist_is_empty_not_error(compat_env):
    res = _sub(_get(compat_env, "getSimilarSongs2", id="ar-00000000000000000000000000000000"))
    # empty result is OK (clients show empty list, never error)
    assert res["similarSongs2"].get("song", []) == []
