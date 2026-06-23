"""T2.3 - Subsonic scrobble + genres + getUser."""

import json
import sqlite3

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return env.client.get(f"/subsonic/rest/{endpoint}", params=q)


def _play_rows(env):
    conn = sqlite3.connect(env.phs.db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM play_history").fetchall()
    finally:
        conn.close()


async def test_scrobble_submission_writes_play_history(compat_env):
    song = _sub(_get(compat_env, "search3", query=""))["searchResult3"]["song"][0]
    _sub(_get(compat_env, "scrobble", id=song["id"], submission="true", c="symfonium"))
    rows = _play_rows(compat_env)
    assert len(rows) == 1
    assert rows[0]["source"] == "symfonium"
    assert rows[0]["release_group_mbid"] == compat_env.ids["rg"]
    assert rows[0]["track_name"] == song["title"]


async def test_scrobble_now_playing_does_not_record(compat_env):
    song = _sub(_get(compat_env, "search3", query=""))["searchResult3"]["song"][0]
    _sub(_get(compat_env, "scrobble", id=song["id"], submission="false"))
    assert _play_rows(compat_env) == []


async def test_scrobble_requires_id(compat_env):
    body = json.loads(_get(compat_env, "scrobble").content)["subsonic-response"]
    assert body["error"]["code"] == 10


async def test_get_genres(compat_env):
    genres = _sub(_get(compat_env, "getGenres"))["genres"]["genre"]
    rock = next(g for g in genres if g["value"] == "Alternative Rock")
    assert rock["songCount"] == 2
    assert rock["albumCount"] == 1


async def test_get_songs_by_genre(compat_env):
    songs = _sub(_get(compat_env, "getSongsByGenre", genre="Alternative Rock"))[
        "songsByGenre"
    ]["song"]
    assert len(songs) == 2
    # case-insensitive match
    songs_ci = _sub(_get(compat_env, "getSongsByGenre", genre="alternative rock"))[
        "songsByGenre"
    ]["song"]
    assert len(songs_ci) == 2


async def test_get_songs_by_genre_requires_genre(compat_env):
    body = json.loads(_get(compat_env, "getSongsByGenre").content)["subsonic-response"]
    assert body["error"]["code"] == 10


async def test_get_user_flags(compat_env):
    user = _sub(_get(compat_env, "getUser", username="alice"))["user"]
    assert user["username"] == "alice"
    assert user["adminRole"] is False
    assert user["streamRole"] is True
    assert user["playlistRole"] is True
    assert user["scrobblingEnabled"] is True
    assert user["maxBitRate"] == 320


async def test_get_user_other_user_forbidden(compat_env):
    body = json.loads(_get(compat_env, "getUser", username="bob").content)["subsonic-response"]
    assert body["error"]["code"] == 50
