"""T5.1 - Jellyfin favorites + played (both dialects) + Q27 cross-protocol."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _h(env):
    return {"Authorization": f'MediaBrowser Token="{env.secret}", Client="pytest"'}


def _jget(env, path, **params):
    r = env.client.get(f"/jellyfin{path}", params=params, headers=_h(env))
    assert r.status_code == 200, r.content
    return json.loads(r.content)


def _track_id(env):
    album_id = _jget(env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]["Id"]
    return _jget(env, "/Items", ParentId=album_id)["Items"][0]["Id"]


async def test_favorite_legacy_form_then_userdata(compat_env):
    tid = _track_id(compat_env)
    r = compat_env.client.post(
        f"/jellyfin/Users/user-alice/FavoriteItems/{tid}", headers=_h(compat_env)
    )
    assert r.status_code == 200
    assert json.loads(r.content)["IsFavorite"] is True
    # reflected on the next item query
    item = _jget(compat_env, f"/Items/{tid}")
    assert item["UserData"]["IsFavorite"] is True


async def test_favorite_modern_form_and_unfavorite(compat_env):
    tid = _track_id(compat_env)
    r = compat_env.client.post(
        f"/jellyfin/UserFavoriteItems/{tid}", params={"userId": "user-alice"},
        headers=_h(compat_env),
    )
    assert r.status_code == 200 and json.loads(r.content)["IsFavorite"] is True
    d = compat_env.client.delete(
        f"/jellyfin/UserFavoriteItems/{tid}", params={"userId": "user-alice"},
        headers=_h(compat_env),
    )
    assert d.status_code == 200 and json.loads(d.content)["IsFavorite"] is False
    assert _jget(compat_env, f"/Items/{tid}")["UserData"]["IsFavorite"] is False


async def test_played_marker_returns_userdata(compat_env):
    tid = _track_id(compat_env)
    r = compat_env.client.post(
        f"/jellyfin/UserPlayedItems/{tid}", params={"userId": "user-alice"},
        headers=_h(compat_env),
    )
    assert r.status_code == 200
    assert json.loads(r.content)["Played"] is True


async def test_favorite_unknown_item_404(compat_env):
    r = compat_env.client.post(
        "/jellyfin/UserFavoriteItems/00000000000000000000000000000000",
        headers=_h(compat_env),
    )
    assert r.status_code == 404


async def test_favorites_unified_across_protocols(compat_env):
    # Q27: a Subsonic star and a Jellyfin item are the SAME user_favorites row
    song = json.loads(compat_env.client.get(
        "/subsonic/rest/search3",
        params={"v": "1.16.1", "c": "x", "f": "json", "apiKey": compat_env.secret, "query": ""},
    ).content)["subsonic-response"]["searchResult3"]["song"][0]
    file_id = song["id"][3:]  # strip tr-
    # star via Subsonic
    compat_env.client.get("/subsonic/rest/star", params={
        "v": "1.16.1", "c": "x", "f": "json", "apiKey": compat_env.secret, "id": song["id"]})
    # the same track via Jellyfin reports IsFavorite:true
    jf_id = await compat_env.id_map.to_jf("track", file_id)
    item = _jget(compat_env, f"/Items/{jf_id}")
    assert item["UserData"]["IsFavorite"] is True
    # native FavoritesService sees the same row
    assert await compat_env.favorites.is_favorite("user-alice", "track", file_id) is True
