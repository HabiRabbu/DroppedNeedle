import json

import pytest

from api.compat.subsonic.ids import encode
from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


@pytest.mark.asyncio
async def test_playback_report_accepts_pinned_form_contract(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    response = compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        data={
            **subsonic_query(compat_env.secret, "alice"),
            "mediaId": track_id,
            "mediaType": "song",
            "positionMs": "1000",
            "state": "starting",
            "playbackRate": "1.0",
        },
    )
    assert _body(response)["status"] == "ok"


@pytest.mark.asyncio
async def test_playback_report_accepts_dedicated_json_body_with_query_auth(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    response = compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        params=subsonic_query(compat_env.secret, "alice"),
        json={
            "mediaId": track_id,
            "mediaType": "song",
            "positionMs": 100_500,
            "state": "stopped",
            "playbackRate": 1,
            "ignoreScrobble": True,
        },
    )
    assert _body(response)["status"] == "ok"


@pytest.mark.asyncio
async def test_playback_report_rejects_podcast_unknown_fields_and_missing_song(compat_env):
    query = subsonic_query(compat_env.secret, "alice")
    track_id = encode("track", compat_env.ids["tracks"][0])
    podcast = _body(compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        params=query,
        json={"mediaId": track_id, "mediaType": "podcast", "positionMs": 0,
              "state": "playing"},
    ))
    assert podcast["status"] == "failed"

    unknown = _body(compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        params=query,
        json={"mediaId": track_id, "mediaType": "song", "positionMs": 0,
              "state": "playing", "credential": "forbidden"},
    ))
    assert unknown["status"] == "failed"

    missing = _body(compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        params=query,
        json={"mediaId": encode("track", "missing"), "mediaType": "song",
              "positionMs": 0, "state": "playing"},
    ))
    assert missing["status"] == "failed"
    assert missing["error"]["code"] == 70


@pytest.mark.asyncio
async def test_playback_report_and_legacy_scrobble_do_not_double_count(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    query = subsonic_query(compat_env.secret, "alice")
    stopped = {
        "mediaId": track_id,
        "mediaType": "song",
        "positionMs": 110_000,
        "state": "stopped",
    }
    assert _body(compat_env.client.post(
        "/subsonic/rest/reportPlayback", params=query, json=stopped
    ))["status"] == "ok"
    assert _body(compat_env.client.post(
        "/subsonic/rest/scrobble", params={**query, "id": track_id}
    ))["status"] == "ok"

    assert len(await compat_env.phs.recent("user-alice")) == 1
