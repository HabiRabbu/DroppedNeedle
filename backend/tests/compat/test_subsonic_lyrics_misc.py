"""Subsonic lyrics (songLyrics ext), tokenInfo, scan status and P4 stubs."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, *, fmt="json", **extra):
    q = {"v": "1.16.1", "c": "pytest", "apiKey": env.secret, **extra}
    if fmt:
        q["f"] = fmt
    return env.client.get(f"/subsonic/rest/{endpoint}", params=q)


def _track_id(env):
    return f"tr-{env.ids['tracks'][0]}"


# ----- lyrics -----


async def test_get_lyrics_by_song_id(compat_env):
    body = _sub(_get(compat_env, "getLyricsBySongId", id=_track_id(compat_env)))
    sl = body["lyricsList"]["structuredLyrics"]
    assert len(sl) == 1
    assert sl[0]["synced"] is True
    assert sl[0]["displayTitle"] == "Airbag"
    assert sl[0]["line"][0] == {"value": "Line one", "start": 0}
    assert sl[0]["line"][1] == {"value": "Line two", "start": 12500}


async def test_get_lyrics_by_song_id_unknown_is_70(compat_env):
    body = _sub(_get(compat_env, "getLyricsBySongId", id="tr-nope"))
    assert body["error"]["code"] == 70


async def test_get_lyrics_by_song_id_xml(compat_env):
    r = _get(compat_env, "getLyricsBySongId", id=_track_id(compat_env), fmt=None)
    text = r.content.decode()
    assert r.headers["content-type"].startswith("application/xml")
    assert "<structuredLyrics" in text
    assert '<line start="12500">Line two</line>' in text


async def test_get_lyrics_legacy_by_artist_title(compat_env):
    body = _sub(_get(compat_env, "getLyrics", artist="Radiohead", title="Airbag"))
    lyr = body["lyrics"]
    assert lyr["title"] == "Airbag"
    assert "Line one" in lyr["value"]


async def test_get_lyrics_legacy_no_match_is_empty_ok(compat_env):
    body = _sub(_get(compat_env, "getLyrics", artist="Nobody", title="Nothing"))
    assert body["status"] == "ok"
    assert "value" not in body["lyrics"]


async def test_extensions_advertise_song_lyrics(compat_env):
    r = compat_env.client.get(
        "/subsonic/rest/getOpenSubsonicExtensions", params={"f": "json"}
    )
    names = {e["name"] for e in _sub(r)["openSubsonicExtensions"]}
    assert "songLyrics" in names


# ----- tokenInfo / scan status / now playing -----


async def test_token_info_returns_username(compat_env):
    assert _sub(_get(compat_env, "tokenInfo"))["tokenInfo"]["username"] == "alice"


async def test_get_scan_status(compat_env):
    st = _sub(_get(compat_env, "getScanStatus"))["scanStatus"]
    assert st["scanning"] is False
    assert st["count"] == 2


async def test_start_scan_reports_state_without_scanning(compat_env):
    st = _sub(_get(compat_env, "startScan"))["scanStatus"]
    assert st["scanning"] is False


async def test_get_now_playing_empty_valid(compat_env):
    body = _sub(_get(compat_env, "getNowPlaying"))
    assert body["status"] == "ok"
    assert body["nowPlaying"] == {"entry": []}


# ----- artist/album info + avatar + old search + users -----


async def test_get_artist_info2_known_artist(compat_env):
    artists = _sub(_get(compat_env, "getArtists"))["artists"]["index"]
    artist_id = artists[0]["artist"][0]["id"]
    body = _sub(_get(compat_env, "getArtistInfo2", id=artist_id))
    assert body["status"] == "ok"
    assert "artistInfo2" in body


async def test_get_artist_info2_unknown_is_70(compat_env):
    body = _sub(_get(compat_env, "getArtistInfo2", id="ar-nope"))
    assert body["error"]["code"] == 70


async def test_get_album_info2_known_album(compat_env):
    body = _sub(_get(compat_env, "getAlbumInfo2", id=f"al-{compat_env.ids['rg']}"))
    assert body["status"] == "ok"
    assert "albumInfo" in body


async def test_get_avatar_returns_image(compat_env):
    r = _get(compat_env, "getAvatar", username="alice")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


async def test_old_search_matches_songs(compat_env):
    res = _sub(_get(compat_env, "search", any="Airbag"))["searchResult"]
    assert res["totalHits"] >= 1
    assert any(mch["title"] == "Airbag" for mch in res["match"])


async def test_get_users_non_admin_is_50(compat_env):
    body = _sub(_get(compat_env, "getUsers"))
    assert body["error"]["code"] == 50


# ----- P4 stubs: valid-empty, never 404/500 -----


@pytest.mark.parametrize("endpoint,key", [
    ("getPodcasts", "podcasts"),
    ("getNewestPodcasts", "newestPodcasts"),
    ("getInternetRadioStations", "internetRadioStations"),
    ("getChatMessages", "chatMessages"),
    ("getShares", "shares"),
    ("getVideos", "videos"),
])
async def test_empty_stub_json_and_xml(compat_env, endpoint, key):
    body = _sub(_get(compat_env, endpoint))
    assert body["status"] == "ok"
    assert body[key] == {}
    r = _get(compat_env, endpoint, fmt=None)
    text = r.content.decode()
    assert r.headers["content-type"].startswith("application/xml")
    assert f"<{key}/>" in text


async def test_add_chat_message_accepted(compat_env):
    assert _sub(_get(compat_env, "addChatMessage", message="hi"))["status"] == "ok"


async def test_jukebox_control_status_and_get(compat_env):
    st = _sub(_get(compat_env, "jukeboxControl", action="status"))["jukeboxStatus"]
    assert st["playing"] is False
    pl = _sub(_get(compat_env, "jukeboxControl", action="get"))["jukeboxPlaylist"]
    assert pl["currentIndex"] == 0


@pytest.mark.parametrize("endpoint", [
    "createShare", "updateShare", "deleteShare",
    "refreshPodcasts", "createPodcastChannel", "deletePodcastChannel",
    "deletePodcastEpisode", "downloadPodcastEpisode",
    "createInternetRadioStation", "updateInternetRadioStation",
    "deleteInternetRadioStation",
    "createUser", "updateUser", "deleteUser", "changePassword",
    "hls",
])
async def test_unsupported_endpoints_return_subsonic_error(compat_env, endpoint):
    body = _sub(_get(compat_env, endpoint))
    assert body["status"] == "failed"
    assert body["error"]["code"] == 0  # correct Subsonic error, not 404/500


@pytest.mark.parametrize("endpoint", ["getVideoInfo", "getCaptions"])
async def test_video_endpoints_return_not_found(compat_env, endpoint):
    body = _sub(_get(compat_env, endpoint, id="42"))
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70
