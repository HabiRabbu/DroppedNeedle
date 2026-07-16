import json

import pytest

from api.compat.subsonic.ids import encode
from api.v1.schemas.settings import ConnectAppsSettings
from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


async def _chunks(value: bytes):
    yield value


def _client_info():
    return {
        "name": "OpenSubsonic test client",
        "platform": "pytest",
        "maxAudioBitrate": 1_000_000,
        "maxTranscodingAudioBitrate": 192_000,
        "directPlayProfiles": [
            {
                "containers": ["flac"],
                "audioCodecs": ["flac"],
                "protocols": ["http"],
                "maxAudioChannels": 2,
            }
        ],
        "transcodingProfiles": [
            {"container": "mp3", "audioCodec": "mp3", "protocol": "http"}
        ],
        "codecProfiles": [],
    }


@pytest.mark.asyncio
async def test_transcode_decision_and_stream_use_scoped_opaque_params(
    compat_env, monkeypatch
):
    monkeypatch.setattr(
        "services.compat.advanced_transcode_service.ffmpeg_available", lambda: True
    )
    compat_env.preferences.save_connect_apps_settings(
        ConnectAppsSettings(
            subsonic_enabled=True,
            jellyfin_enabled=True,
            transcoding_enabled=True,
            transcode_max_bitrate_kbps=256,
        )
    )
    query = {
        **subsonic_query(compat_env.secret, "alice"),
        "mediaId": encode("track", compat_env.ids["tracks"][0]),
        "mediaType": "song",
    }
    decision = _body(compat_env.client.post(
        "/subsonic/rest/getTranscodeDecision", params=query, json=_client_info()
    ))["transcodeDecision"]

    assert decision["canDirectPlay"] is True
    assert decision["canTranscode"] is False
    assert decision["sourceStream"]["codec"] == "flac"
    assert decision["sourceStream"]["audioBitrate"] == 900_000
    token = decision["transcodeParams"]
    assert "track" not in token

    compat_env.local_files.stream_track.return_value = (
        _chunks(b"direct"),
        {"Content-Type": "audio/flac", "Content-Length": "6"},
        200,
    )
    streamed = compat_env.client.get(
        "/subsonic/rest/getTranscodeStream",
        params={**query, "transcodeParams": token, "offset": 12},
    )
    assert streamed.status_code == 200
    assert streamed.content == b"direct"
    compat_env.transcode.stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcode_contract_rejects_unknown_json_and_cross_user_token(
    compat_env, monkeypatch
):
    monkeypatch.setattr(
        "services.compat.advanced_transcode_service.ffmpeg_available", lambda: True
    )
    compat_env.preferences.save_connect_apps_settings(
        ConnectAppsSettings(
            subsonic_enabled=True,
            jellyfin_enabled=True,
            transcoding_enabled=True,
        )
    )
    query = {
        **subsonic_query(compat_env.secret, "alice"),
        "mediaId": encode("track", compat_env.ids["tracks"][0]),
        "mediaType": "song",
    }
    invalid = {**_client_info(), "unknown": True}
    assert _body(compat_env.client.post(
        "/subsonic/rest/getTranscodeDecision", params=query, json=invalid
    ))["status"] == "failed"

    decision = _body(compat_env.client.post(
        "/subsonic/rest/getTranscodeDecision", params=query, json=_client_info()
    ))["transcodeDecision"]
    _record, bob_secret = await compat_env.app_passwords.create(
        "user-bob", "bob transcode"
    )
    bob_query = {
        **subsonic_query(bob_secret, "bob"),
        "mediaId": query["mediaId"],
        "mediaType": "song",
        "transcodeParams": decision["transcodeParams"],
    }
    denied = _body(compat_env.client.get(
        "/subsonic/rest/getTranscodeStream", params=bob_query
    ))
    assert denied["status"] == "failed"
    compat_env.transcode.stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcode_decision_executes_transcode_token_with_seek(
    compat_env, monkeypatch
):
    from pathlib import Path

    from fastapi.responses import Response

    monkeypatch.setattr(
        "services.compat.advanced_transcode_service.ffmpeg_available", lambda: True
    )
    compat_env.preferences.save_connect_apps_settings(
        ConnectAppsSettings(
            subsonic_enabled=True,
            jellyfin_enabled=True,
            transcoding_enabled=True,
            transcode_max_bitrate_kbps=256,
        )
    )
    query = {
        **subsonic_query(compat_env.secret, "alice"),
        "mediaId": encode("track", compat_env.ids["tracks"][0]),
        "mediaType": "song",
    }
    client_info = {**_client_info(), "directPlayProfiles": []}
    decision = _body(compat_env.client.post(
        "/subsonic/rest/getTranscodeDecision", params=query, json=client_info
    ))["transcodeDecision"]
    assert decision["canDirectPlay"] is False
    assert decision["canTranscode"] is True
    assert decision["transcodeStream"]["audioBitrate"] == 192_000

    compat_env.local_files.resolve_validated_path.return_value = Path("/safe/song.flac")
    compat_env.transcode.stream.return_value = Response(
        b"transcoded", media_type="audio/mpeg"
    )
    streamed = compat_env.client.get(
        "/subsonic/rest/getTranscodeStream",
        params={
            **query,
            "transcodeParams": decision["transcodeParams"],
            "offset": 12,
        },
    )
    assert streamed.status_code == 200
    assert streamed.content == b"transcoded"
    plan = compat_env.transcode.stream.await_args.args[1]
    assert plan.out_format == "mp3"
    assert plan.start_seconds == 12
