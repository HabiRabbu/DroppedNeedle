import json

import pytest

from api.compat.subsonic.ids import encode
from services.compat.native_lyrics_service import NativeLyrics, NativeLyricsLine
from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


@pytest.mark.asyncio
async def test_song_lyrics_v1_json_contract(compat_env):
    compat_env.lyrics.get.return_value = NativeLyrics(
        "eng",
        True,
        (NativeLyricsLine("first", 100), NativeLyricsLine("second", 250)),
        "sidecar",
    )
    track_id = encode("track", compat_env.ids["tracks"][0])
    body = _body(compat_env.client.get(
        "/subsonic/rest/getLyricsBySongId",
        params={**subsonic_query(compat_env.secret, "alice"), "id": track_id},
    ))

    structured = body["lyricsList"]["structuredLyrics"][0]
    assert structured["lang"] == "eng"
    assert structured["synced"] is True
    assert structured["line"] == [
        {"value": "first", "start": 100},
        {"value": "second", "start": 250},
    ]
    assert "cueLine" not in structured
    assert "kind" not in structured


@pytest.mark.asyncio
async def test_lyrics_missing_song_and_empty_native_lyrics_are_distinct(compat_env):
    query = subsonic_query(compat_env.secret, "alice")
    missing = _body(compat_env.client.get(
        "/subsonic/rest/getLyricsBySongId",
        params={**query, "id": encode("track", "missing")},
    ))
    assert missing["status"] == "failed"
    assert missing["error"]["code"] == 70

    existing = _body(compat_env.client.get(
        "/subsonic/rest/getLyricsBySongId",
        params={**query, "id": encode("track", compat_env.ids["tracks"][0])},
    ))
    assert existing["lyricsList"]["structuredLyrics"] == []


@pytest.mark.asyncio
async def test_legacy_lyrics_resolves_exact_title_and_artist(compat_env):
    compat_env.lyrics.get.return_value = NativeLyrics(
        "und", False, (NativeLyricsLine("hello"), NativeLyricsLine("world")), "embedded"
    )
    body = _body(compat_env.client.get(
        "/subsonic/rest/getLyrics",
        params={
            **subsonic_query(compat_env.secret, "alice"),
            "artist": "Radiohead",
            "title": "Airbag",
        },
    ))

    assert body["lyrics"] == {
        "artist": "Radiohead",
        "title": "Airbag",
        "value": "hello\nworld",
    }
