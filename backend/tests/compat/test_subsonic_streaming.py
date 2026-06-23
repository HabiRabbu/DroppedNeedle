"""T1.5 - Subsonic direct stream + download (Range/206/416, GZip-vs-Range).

The ``streaming_env`` fixture (real FLAC on disk, both shims, GZipMiddleware)
lives in conftest.py and is shared with the Jellyfin stream tests.
"""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _q(env, **extra):
    return {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}


async def test_range_returns_206_with_content_range(streaming_env):
    r = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert r.headers["Content-Range"] == f"bytes 0-99/{len(streaming_env.raw)}"
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.content == streaming_env.raw[0:100]


async def test_full_stream_200_and_accept_ranges(streaming_env):
    r = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
    )
    assert r.status_code == 200
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers["Content-Type"] == "audio/flac"


async def test_gzip_does_not_compress_audio(streaming_env):
    # client explicitly accepts gzip; the shim must NOT gzip audio (05 s10)
    r = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
        headers={"Accept-Encoding": "gzip"},
    )
    assert r.status_code == 200
    assert r.headers.get("Content-Encoding", "identity") == "identity"
    assert r.content == streaming_env.raw  # byte-identical, not inflated-from-gzip


async def test_format_raw_serves_original_bytes(streaming_env):
    r = streaming_env.client.get(
        "/subsonic/rest/stream",
        params=_q(streaming_env, id=streaming_env.track_id, format="raw"),
    )
    assert r.status_code == 200
    assert r.content == streaming_env.raw


async def test_download_is_byte_identical(streaming_env):
    r = streaming_env.client.get(
        "/subsonic/rest/download", params=_q(streaming_env, id=streaming_env.track_id),
    )
    assert r.status_code == 200
    assert r.content == streaming_env.raw


async def test_range_then_reassemble_full_file(streaming_env):
    total = len(streaming_env.raw)
    mid = total // 2
    r1 = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
        headers={"Range": f"bytes=0-{mid - 1}"},
    )
    r2 = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
        headers={"Range": f"bytes={mid}-"},
    )
    assert r1.status_code == 206 and r2.status_code == 206
    assert r1.content + r2.content == streaming_env.raw


async def test_unknown_track_is_404(streaming_env):
    r = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id="tr-does-not-exist"),
    )
    assert r.status_code == 404


async def test_unsatisfiable_range_is_416(streaming_env):
    big = len(streaming_env.raw) + 1000
    r = streaming_env.client.get(
        "/subsonic/rest/stream", params=_q(streaming_env, id=streaming_env.track_id),
        headers={"Range": f"bytes={big}-"},
    )
    assert r.status_code == 416


# ----- T3.2: transcode wiring + graceful degradation -----

async def test_format_mp3_degrades_to_direct_when_ffmpeg_absent(streaming_env):
    # ffmpeg is absent on this box -> format=mp3 must serve original bytes (05 s9)
    import services.compat.transcode_service as ts

    if ts.ffmpeg_available():
        pytest.skip("ffmpeg present; degradation path not exercised here")
    r = streaming_env.client.get(
        "/subsonic/rest/stream",
        params=_q(streaming_env, id=streaming_env.track_id, format="mp3", maxBitRate="128"),
    )
    assert r.status_code in (200, 206)
    assert r.content == streaming_env.raw


async def test_transcoding_disabled_serves_original(streaming_env):
    from api.v1.schemas.settings import ConnectAppsSettings

    streaming_env.prefs.save_connect_apps_settings(
        ConnectAppsSettings(subsonic_enabled=True, transcoding_enabled=False)
    )
    r = streaming_env.client.get(
        "/subsonic/rest/stream",
        params=_q(streaming_env, id=streaming_env.track_id, format="mp3", maxBitRate="128"),
    )
    assert r.content == streaming_env.raw


async def test_format_mp3_invokes_transcode_when_available(streaming_env, monkeypatch):
    # force "ffmpeg present" + a stub transcode service to prove the wiring without
    # needing a real ffmpeg binary
    import services.compat.transcode_service as ts
    from core import dependencies as deps
    from fastapi.responses import Response

    monkeypatch.setattr(ts, "ffmpeg_available", lambda: True)
    captured = {}

    class _StubTranscode:
        def stream(self, path, plan, *, is_disconnected=None, estimate=False):
            captured["path"] = path
            captured["plan"] = plan
            return Response(content=b"TRANSCODED", media_type="audio/mpeg",
                            headers={"Accept-Ranges": "none"})

    streaming_env.app.dependency_overrides[deps.get_transcode_service] = _StubTranscode
    try:
        r = streaming_env.client.get(
            "/subsonic/rest/stream",
            params=_q(streaming_env, id=streaming_env.track_id, format="mp3", maxBitRate="128"),
        )
    finally:
        streaming_env.app.dependency_overrides.pop(deps.get_transcode_service, None)
    assert r.content == b"TRANSCODED"
    assert r.headers["Accept-Ranges"] == "none"
    plan = captured["plan"]
    assert plan.transcode is True
    assert plan.out_format == "mp3"
    assert plan.out_bitrate_kbps == 128
    assert captured["path"].endswith("flac_full_01.flac")


async def test_child_advertises_transcoded_fields_when_available(streaming_env, monkeypatch):
    import services.compat.transcode_service as ts

    monkeypatch.setattr(ts, "ffmpeg_available", lambda: True)
    q = _q(streaming_env, id=streaming_env.track_id)
    song = json.loads(
        streaming_env.client.get("/subsonic/rest/getSong", params=q).content
    )["subsonic-response"]["song"]
    assert song["transcodedSuffix"] == "mp3"
    assert song["transcodedContentType"] == "audio/mpeg"

