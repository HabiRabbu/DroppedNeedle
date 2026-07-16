import json

import pytest

from api.compat.subsonic.ids import encode
from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


@pytest.mark.asyncio
async def test_song_exposes_truthful_rich_metadata_and_replaygain(compat_env):
    await compat_env.phs.insert(
        "user-alice",
        track_name="Airbag",
        artist_name="Radiohead",
        album_name="OK Computer",
        recording_mbid="rec-1",
        release_group_mbid=compat_env.ids["rg"],
        played_at="2026-07-13T10:00:00+00:00",
    )
    track_id = encode("track", compat_env.ids["tracks"][0])
    song = _body(compat_env.client.get(
        "/subsonic/rest/getSong",
        params={**subsonic_query(compat_env.secret, "alice"), "id": track_id},
    ))["song"]

    assert song["artist"] == "Radiohead"
    assert song["displayArtist"] == "Radiohead"
    assert song["artists"][0]["name"] == "Radiohead"
    assert song["displayAlbumArtist"] == "Radiohead"
    assert song["genres"] == [{"name": "Alternative Rock"}]
    assert song["sortName"] == "Airbag, The"
    assert song["playCount"] == 1
    assert song["played"] == "2026-07-13T10:00:00Z"
    assert song["replayGain"] == {
        "trackGain": -7.25,
        "albumGain": -6.5,
        "trackPeak": 0.98,
        "albumPeak": 0.99,
    }


@pytest.mark.asyncio
async def test_album_exposes_original_date_disc_title_and_batched_play_overlay(compat_env):
    await compat_env.phs.insert(
        "user-alice",
        track_name="Airbag",
        artist_name="Radiohead",
        album_name="OK Computer",
        recording_mbid="rec-1",
        release_group_mbid=compat_env.ids["rg"],
        played_at="2026-07-13T11:00:00+00:00",
    )
    album = _body(compat_env.client.get(
        "/subsonic/rest/getAlbum",
        params={
            **subsonic_query(compat_env.secret, "alice"),
            "id": encode("album", compat_env.ids["rg"]),
        },
    ))["album"]

    assert album["originalReleaseDate"] == {"year": 1997, "month": 5, "day": 21}
    assert album["discTitles"] == [{"disc": 1, "title": "Main Album"}]
    assert album["playCount"] == 1
    assert album["played"] == "2026-07-13T11:00:00Z"
