"""T3.1 - TranscodeService: decide() policy, ffmpeg argv, estimate, real output."""

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from api.v1.schemas.settings import ConnectAppsSettings
from services.compat.transcode_service import (
    TranscodeService,
    build_cmd,
    decide,
    ffmpeg_available,
    _estimate_size,
    out_media_type,
    out_suffix,
)
from services.compat.stream_concurrency import StreamConcurrencyService
from services.compat.view_models import ViewTrack

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_needs_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _track(**over) -> ViewTrack:
    base = dict(file_id="f1", title="T", album_title="A", file_format="flac",
                bitrate=900, duration_seconds=200.0)
    base.update(over)
    return ViewTrack(**base)


def _settings(**over) -> ConnectAppsSettings:
    base = dict(transcoding_enabled=True, transcode_default_format="mp3",
                transcode_max_bitrate_kbps=320)
    base.update(over)
    return ConnectAppsSettings(**base)


# ----- decide() policy -----

def test_force_original_never_transcodes():
    plan = decide(_track(), requested_format="mp3", max_bitrate_kbps=128,
                  force_original=True, start_seconds=0, settings=_settings(),
                  ffmpeg_available=True)
    assert plan.transcode is False


def test_transcoding_disabled_degrades():
    plan = decide(_track(), requested_format="mp3", max_bitrate_kbps=128,
                  force_original=False, start_seconds=0,
                  settings=_settings(transcoding_enabled=False), ffmpeg_available=True)
    assert plan.transcode is False


def test_ffmpeg_absent_degrades():
    plan = decide(_track(), requested_format="mp3", max_bitrate_kbps=128,
                  force_original=False, start_seconds=0, settings=_settings(),
                  ffmpeg_available=False)
    assert plan.transcode is False


def test_bitrate_cap_below_source_transcodes():
    plan = decide(_track(bitrate=900), requested_format=None, max_bitrate_kbps=128,
                  force_original=False, start_seconds=0, settings=_settings(),
                  ffmpeg_available=True)
    assert plan.transcode is True
    assert plan.out_format == "mp3"  # default
    assert plan.out_bitrate_kbps == 128


def test_codec_change_transcodes_to_requested():
    plan = decide(_track(file_format="mp3", bitrate=192), requested_format="opus",
                  max_bitrate_kbps=0, force_original=False, start_seconds=0,
                  settings=_settings(), ffmpeg_available=True)
    assert plan.transcode is True
    assert plan.out_format == "opus"
    assert plan.out_bitrate_kbps == 320  # codec change, no cap -> configured max


def test_no_cap_no_mismatch_is_direct():
    plan = decide(_track(file_format="mp3", bitrate=192), requested_format=None,
                  max_bitrate_kbps=0, force_original=False, start_seconds=0,
                  settings=_settings(), ffmpeg_available=True)
    assert plan.transcode is False


def test_lossless_over_server_cap_still_direct_plays():
    # Jellify regression: a FLAC at 900kbps exceeds the 320 server cap, but with no codec
    # change and no CLIENT bitrate cap it must DIRECT-play (the server cap only clamps when
    # transcoding, it never forces one) - else direct-play clients break.
    plan = decide(_track(file_format="flac", bitrate=900), requested_format=None,
                  max_bitrate_kbps=0, force_original=False, start_seconds=0,
                  settings=_settings(transcode_max_bitrate_kbps=320), ffmpeg_available=True)
    assert plan.transcode is False


def test_codec_request_transcodes_and_clamps_to_server_cap():
    # Manet: /universal?AudioCodec=mp3 on a FLAC -> transcode to mp3, output clamped to the
    # server's transcode_max_bitrate_kbps even though the client gave no bitrate.
    plan = decide(_track(file_format="flac", bitrate=900), requested_format="mp3",
                  max_bitrate_kbps=0, force_original=False, start_seconds=0,
                  settings=_settings(transcode_max_bitrate_kbps=320), ffmpeg_available=True)
    assert plan.transcode is True
    assert plan.out_format == "mp3" and plan.out_bitrate_kbps == 320


def test_unsupported_requested_format_falls_back_to_default():
    plan = decide(_track(file_format="flac"), requested_format="aac",
                  max_bitrate_kbps=256, force_original=False, start_seconds=0,
                  settings=_settings(transcode_default_format="opus"),
                  ffmpeg_available=True)
    assert plan.transcode is True
    assert plan.out_format == "opus"


def test_bitrate_clamped_to_floor():
    plan = decide(_track(bitrate=900), requested_format="mp3", max_bitrate_kbps=8,
                  force_original=False, start_seconds=0, settings=_settings(),
                  ffmpeg_available=True)
    assert plan.out_bitrate_kbps == 64  # floor


def test_start_seconds_only_on_transcode():
    plan = decide(_track(bitrate=900), requested_format="mp3", max_bitrate_kbps=128,
                  force_original=False, start_seconds=30.0, settings=_settings(),
                  ffmpeg_available=True)
    assert plan.transcode is True and plan.start_seconds == 30.0


# ----- argv + helpers -----

def test_mp3_argv():
    from services.compat.transcode_service import StreamPlan

    cmd = build_cmd("/m/x.flac", StreamPlan(transcode=True, out_format="mp3",
                                            out_bitrate_kbps=128, start_seconds=0))
    assert cmd[0] == "ffmpeg"
    assert "libmp3lame" in cmd and "-b:a" in cmd and "128k" in cmd
    assert cmd[-3:] == ["-f", "mp3", "pipe:1"]
    assert "-ss" not in cmd  # no seek


def test_opus_argv_with_seek():
    from services.compat.transcode_service import StreamPlan

    cmd = build_cmd("/m/x.flac", StreamPlan(transcode=True, out_format="opus",
                                            out_bitrate_kbps=160, start_seconds=12.5))
    assert "libopus" in cmd
    assert cmd[cmd.index("-ss") + 1] == "12.500"
    assert cmd[-3:] == ["-f", "ogg", "pipe:1"]


def test_media_type_and_suffix():
    assert out_media_type("mp3") == "audio/mpeg"
    assert out_media_type("opus") == "audio/ogg"
    assert out_suffix("mp3") == "mp3" and out_suffix("opus") == "opus"


def test_estimate_size_accounts_for_seek():
    from services.compat.transcode_service import StreamPlan

    plan = StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128,
                      start_seconds=10.0, source_duration_seconds=210.0)
    # 128kbit/s * 200s = 128000/8 * 200 bytes
    assert _estimate_size(plan) == int(128 * 1000 / 8 * 200.0)


def test_ffmpeg_available_matches_environment():
    assert ffmpeg_available() == (shutil.which("ffmpeg") is not None)


# ----- real transcode (ffprobe-gated) -----

@pytest.mark.asyncio
@_needs_ffmpeg
async def test_transcode_produces_decodable_mp3():
    src = Path(__file__).parent.parent / "fixtures" / "library" / "flac_full_01.flac"
    from services.compat.transcode_service import StreamPlan

    svc = TranscodeService(StreamConcurrencyService())
    plan = StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128,
                      start_seconds=0, source_duration_seconds=0.3)
    resp = await svc.stream(str(src), plan, principal="user-1")
    assert resp.headers["Accept-Ranges"] == "none"
    assert resp.media_type == "audio/mpeg"
    body = b"".join([chunk async for chunk in resp.body_iterator])
    assert body  # non-empty transcoded output
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
        tmp.write(body)
        tmp.flush()
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
             "-of", "default=nw=1:nk=1", tmp.name],
            capture_output=True, text=True,
        )
    assert "mp3" in out.stdout


@pytest.mark.asyncio
@_needs_ffmpeg
async def test_disconnect_reaps_process():
    src = Path(__file__).parent.parent / "fixtures" / "library" / "flac_full_01.flac"
    from services.compat.transcode_service import StreamPlan
    from core.exceptions import ClientDisconnectedError

    svc = TranscodeService(StreamConcurrencyService())
    plan = StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128,
                      start_seconds=0)

    async def disconnected():
        return True  # client already gone

    resp = await svc.stream(
        str(src), plan, principal="user-1", is_disconnected=disconnected
    )
    with pytest.raises(ClientDisconnectedError):
        async for _ in resp.body_iterator:
            pass


@pytest.mark.asyncio
async def test_subprocess_start_failure_releases_transcode_slot(monkeypatch):
    from services.compat.transcode_service import StreamPlan

    concurrency = StreamConcurrencyService(transcode_global_limit=1)
    svc = TranscodeService(concurrency)

    async def fail_start(*_args, **_kwargs):
        raise OSError("ffmpeg unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_start)
    response = await svc.stream(
        "/validated/input.flac",
        StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128),
        principal="alice",
    )
    with pytest.raises(OSError, match="ffmpeg unavailable"):
        await anext(response.body_iterator)
    assert concurrency.transcode.active == 0


@pytest.mark.asyncio
async def test_response_setup_failure_releases_transcode_slot(monkeypatch):
    import services.compat.transcode_service as module
    from services.compat.transcode_service import StreamPlan

    concurrency = StreamConcurrencyService(transcode_global_limit=1)
    svc = TranscodeService(concurrency)

    def fail_build(*_args, **_kwargs):
        raise ValueError("invalid plan")

    monkeypatch.setattr(module, "build_cmd", fail_build)
    with pytest.raises(ValueError, match="invalid plan"):
        await svc.stream(
            "/validated/input.flac",
            StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128),
            principal="alice",
        )
    assert concurrency.transcode.active == 0


class _Pipe:
    def __init__(self, chunks=None, wait_forever: bool = False):
        self.chunks = list(chunks or [])
        self.wait_forever = wait_forever

    async def read(self, _size):
        if self.wait_forever:
            await asyncio.Event().wait()
        return self.chunks.pop(0) if self.chunks else b""


class _Process:
    def __init__(self, *, stdout, stderr=None, returncode=None):
        self.stdout = stdout
        self.stderr = stderr or _Pipe()
        self.returncode = returncode
        self.terminated = False

    async def wait(self):
        if self.returncode is None:
            self.returncode = -15 if self.terminated else 0
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.returncode = -9


@pytest.mark.asyncio
async def test_cancelled_transcode_reaps_process_and_releases_slot(monkeypatch):
    from services.compat.transcode_service import StreamPlan

    concurrency = StreamConcurrencyService(transcode_global_limit=1)
    svc = TranscodeService(concurrency)
    process = _Process(stdout=_Pipe(wait_forever=True))

    async def start(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    response = await svc.stream(
        "/validated/input.flac",
        StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128),
        principal="alice",
    )
    consume = asyncio.create_task(anext(response.body_iterator))
    await asyncio.sleep(0)
    consume.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consume
    assert process.terminated is True
    assert concurrency.transcode.active == 0


@pytest.mark.asyncio
async def test_transcode_read_timeout_reaps_process_and_releases_slot(monkeypatch):
    import services.compat.transcode_service as module
    from services.compat.transcode_service import StreamPlan

    concurrency = StreamConcurrencyService(transcode_global_limit=1)
    svc = TranscodeService(concurrency)
    process = _Process(stdout=_Pipe(wait_forever=True))

    async def start(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    monkeypatch.setattr(module, "_READ_TIMEOUT_S", 0.01)
    response = await svc.stream(
        "/validated/input.flac",
        StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128),
        principal="alice",
    )
    with pytest.raises(TimeoutError):
        await anext(response.body_iterator)
    assert process.terminated is True
    assert concurrency.transcode.active == 0


@pytest.mark.asyncio
async def test_ffmpeg_stderr_is_drained_but_capture_is_bounded(monkeypatch, caplog):
    from services.compat.transcode_service import StreamPlan

    concurrency = StreamConcurrencyService(transcode_global_limit=1)
    svc = TranscodeService(concurrency)
    process = _Process(
        stdout=_Pipe(), stderr=_Pipe([b"x" * 5000]), returncode=1
    )

    async def start(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    response = await svc.stream(
        "/validated/private/input.flac",
        StreamPlan(transcode=True, out_format="mp3", out_bitrate_kbps=128),
        principal="alice",
    )
    with caplog.at_level("WARNING"):
        assert b"".join([chunk async for chunk in response.body_iterator]) == b""
    message = next(record.message for record in caplog.records if "ffmpeg exited" in record.message)
    assert len(message) < 2100
    assert "/validated/private/input.flac" not in message
    assert concurrency.transcode.active == 0
