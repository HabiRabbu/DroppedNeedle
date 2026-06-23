"""On-the-fly transcoding for both compat shims.

Single uvicorn worker, so ffmpeg runs as an asyncio subprocess streamed in
chunks rather than blocking the loop. ``decide()`` is the one place the
direct-play-vs-transcode policy lives.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from functools import lru_cache
from typing import TYPE_CHECKING, AsyncGenerator, Callable

from fastapi.responses import StreamingResponse

from core.exceptions import ClientDisconnectedError
from infrastructure.constants import STREAM_CHUNK_SIZE
from infrastructure.msgspec_fastapi import AppStruct

if TYPE_CHECKING:
    from api.v1.schemas.settings import ConnectAppsSettings
    from services.compat.view_models import ViewTrack

logger = logging.getLogger(__name__)

_SUPPORTED_OUT = {"mp3", "opus"}
_MIN_BITRATE_KBPS = 64
_READ_TIMEOUT_S = 30.0
_HUGE = 10**9  # "no cap" sentinel (Subsonic maxBitRate=0, Finamp 999999999)


@lru_cache(maxsize=1)
def ffmpeg_available() -> bool:
    """Absent => direct play."""
    return shutil.which("ffmpeg") is not None


class StreamPlan(AppStruct):
    transcode: bool
    out_format: str | None = None         # 'mp3' | 'opus' when transcode
    out_bitrate_kbps: int | None = None   # target bitrate when transcode
    start_seconds: float = 0.0            # ffmpeg -ss (transcode only)
    source_duration_seconds: float | None = None


def out_media_type(out_format: str) -> str:
    return "audio/mpeg" if out_format == "mp3" else "audio/ogg"


def out_suffix(out_format: str) -> str:
    return "mp3" if out_format == "mp3" else "opus"


def decide(
    track: "ViewTrack",
    *,
    requested_format: str | None,
    max_bitrate_kbps: int | None,
    force_original: bool,
    start_seconds: float,
    settings: "ConnectAppsSettings",
    ffmpeg_available: bool,
) -> StreamPlan:
    """Direct-play-vs-transcode policy. Rules applied in order."""
    if force_original or not settings.transcoding_enabled or not ffmpeg_available:
        return StreamPlan(transcode=False, start_seconds=0.0,
                          source_duration_seconds=track.duration_seconds)

    # Only an explicit client request triggers a transcode (codec change, or a
    # client max bitrate below source). The server transcode_max_bitrate_kbps is a
    # quality ceiling applied when transcoding, never a trigger - else every
    # lossless file would be force-transcoded and direct-play clients break.
    client_ceiling = (
        max_bitrate_kbps if (max_bitrate_kbps and max_bitrate_kbps > 0) else _HUGE
    )
    src_fmt = (track.file_format or "").lower()
    req = (requested_format or "").lower()
    codec_mismatch = bool(req) and req != "raw" and req != src_fmt
    over_ceiling = client_ceiling < (track.bitrate or 0)

    if not (codec_mismatch or over_ceiling):
        return StreamPlan(transcode=False, start_seconds=0.0,
                          source_duration_seconds=track.duration_seconds)

    out_format = req if req in _SUPPORTED_OUT else settings.transcode_default_format
    bitrate = max(
        min(client_ceiling, settings.transcode_max_bitrate_kbps), _MIN_BITRATE_KBPS
    )
    return StreamPlan(
        transcode=True, out_format=out_format, out_bitrate_kbps=bitrate,
        start_seconds=max(start_seconds, 0.0),
        source_duration_seconds=track.duration_seconds,
    )


def _mp3_cmd(path: str, bitrate_kbps: int, start_s: float) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-ss", f"{start_s:.3f}"] if start_s > 0 else []),
        "-i", path, "-vn", "-map", "0:a:0",
        "-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k", "-f", "mp3", "pipe:1",
    ]


def _opus_cmd(path: str, bitrate_kbps: int, start_s: float) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-ss", f"{start_s:.3f}"] if start_s > 0 else []),
        "-i", path, "-vn", "-map", "0:a:0",
        "-c:a", "libopus", "-b:a", f"{bitrate_kbps}k", "-f", "ogg", "pipe:1",
    ]


def build_cmd(path: str, plan: StreamPlan) -> list[str]:
    builder = _mp3_cmd if plan.out_format == "mp3" else _opus_cmd
    return builder(path, plan.out_bitrate_kbps or _MIN_BITRATE_KBPS, plan.start_seconds)


def _estimate_size(plan: StreamPlan) -> int:
    duration = max((plan.source_duration_seconds or 0.0) - plan.start_seconds, 0.0)
    return int((plan.out_bitrate_kbps or _MIN_BITRATE_KBPS) * 1000 / 8 * duration)


class TranscodeService:
    def __init__(self, semaphore: asyncio.Semaphore) -> None:
        self._sem = semaphore

    def stream(
        self,
        path: str,
        plan: StreamPlan,
        *,
        is_disconnected: Callable | None = None,
        estimate: bool = False,
    ) -> StreamingResponse:
        cmd = build_cmd(path, plan)
        content_type = out_media_type(plan.out_format or "mp3")
        headers = {"Accept-Ranges": "none", "Cache-Control": "no-store",
                   "Content-Encoding": "identity"}
        if estimate:
            headers["Content-Length"] = str(_estimate_size(plan))
        return StreamingResponse(
            self._body(cmd, path, is_disconnected), status_code=200,
            media_type=content_type, headers=headers,
        )

    async def _body(
        self, cmd: list[str], path: str, is_disconnected: Callable | None
    ) -> AsyncGenerator[bytes, None]:
        async with self._sem:  # cap concurrent ffmpeg subprocesses
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                while True:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(STREAM_CHUNK_SIZE), timeout=_READ_TIMEOUT_S
                    )
                    if not chunk:
                        break
                    if is_disconnected is not None and await is_disconnected():
                        raise ClientDisconnectedError("client gone mid-transcode")
                    yield chunk
                rc = await asyncio.wait_for(proc.wait(), timeout=5)
                if rc not in (0, None):
                    err = (await proc.stderr.read()).decode("utf-8", "replace")[:2000]
                    logger.warning("ffmpeg exited %s for %s: %s", rc, path, err)
            finally:
                await self._terminate(proc)

    @staticmethod
    async def _terminate(proc) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass
