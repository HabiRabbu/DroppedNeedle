import asyncio
import hashlib
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock

import pytest

from services.native.replaygain_analysis_service import ReplayGainAnalysisService


def _runner(output: str, *, returncode: int = 0):
    def run(command, _timeout):  # noqa: ANN001
        if "--version" in command:
            return subprocess.CompletedProcess(
                command, 0, stdout="loudgain 0.6.8\n", stderr=""
            )
        return subprocess.CompletedProcess(
            command, returncode, stdout=output, stderr=""
        )

    return run


def _output(first: Path, second: Path) -> str:
    header = (
        "File\tLoudness\tRange\tTrue_Peak\tTrue_Peak_dBTP\tReference\t"
        "Will_clip\tClip_prevent\tGain\tNew_Peak\tNew_Peak_dBTP"
    )
    return "\n".join(
        (
            header,
            f"{first}\t-21.75 LUFS\t0.00 dB\t0.125093\t-18.06 dBTP\t"
            "-18.00 LUFS\tN\tN\t3.75 dB\t0.192705\t-14.30 dBTP",
            f"{second}\t-27.33 LUFS\t0.00 dB\t0.062546\t-24.08 dBTP\t"
            "-18.00 LUFS\tN\tN\t9.33 dB\t0.183022\t-14.75 dBTP",
            "Album\t-23.70 LUFS\t0.00 dB\t0.125093\t-18.06 dBTP\t"
            "-18.00 LUFS\tN\tN\t5.70 dB\t0.241150\t-12.35 dBTP",
        )
    )


@pytest.mark.asyncio
async def test_album_analysis_parses_track_and_album_values_without_source_mutation(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.flac"
    second = tmp_path / "second.flac"
    first.write_bytes(b"first audio")
    second.write_bytes(b"second audio")
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)
    }
    service = ReplayGainAnalysisService(
        executable="/usr/bin/loudgain",
        runner=_runner(_output(first, second)),
    )

    result = await service.analyze((first, second), album_aware=True)

    assert result.status == "available"
    assert result.analyzer_version == "loudgain 0.6.8"
    assert result.tracks[0].track_gain_db == 3.75
    assert result.tracks[0].track_peak == 0.125093
    assert result.tracks[0].album_gain_db == 5.7
    assert result.tracks[0].album_peak == 0.125093
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)
    } == before


@pytest.mark.asyncio
async def test_non_finite_or_failed_analysis_is_deferred(tmp_path: Path) -> None:
    source = tmp_path / "silent.flac"
    source.write_bytes(b"audio")
    invalid = _output(source, source).replace("3.75 dB", "inf dB", 1)

    non_finite = await ReplayGainAnalysisService(
        executable="/usr/bin/loudgain", runner=_runner(invalid)
    ).analyze((source,), album_aware=True)
    failed = await ReplayGainAnalysisService(
        executable="/usr/bin/loudgain", runner=_runner("", returncode=1)
    ).analyze((source,), album_aware=False)
    malformed = await ReplayGainAnalysisService(
        executable="/usr/bin/loudgain", runner=_runner("not tabular output")
    ).analyze((source,), album_aware=False)

    assert non_finite.status == "deferred"
    assert failed.status == "deferred"
    assert malformed.status == "deferred"


@pytest.mark.asyncio
async def test_analyzer_source_change_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "track.flac"
    source.write_bytes(b"audio")

    def mutating_runner(command, _timeout):  # noqa: ANN001
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, stdout="0.6.8", stderr="")
        source.write_bytes(b"changed")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = await ReplayGainAnalysisService(
        executable="/usr/bin/loudgain", runner=mutating_runner
    ).analyze((source,), album_aware=False)

    assert result.status == "deferred"
    assert result.reason == "The analyzer changed a source file."


@pytest.mark.asyncio
async def test_cancellation_reaps_analyzer_before_releasing_concurrency_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "track.flac"
    source.write_bytes(b"audio")
    started = asyncio.Event()
    terminated = asyncio.Event()
    allow_exit = asyncio.Event()

    class VersionProcess:
        returncode = 0

        async def communicate(self):
            return b"loudgain 0.6.8\n", b""

    class AnalysisProcess:
        returncode = None

        async def communicate(self):
            started.set()
            await asyncio.Future()

        def terminate(self) -> None:
            terminated.set()

        def kill(self) -> None:
            self.returncode = -9
            allow_exit.set()

        async def wait(self) -> int:
            await allow_exit.wait()
            self.returncode = -15
            return self.returncode

    analysis = AnalysisProcess()
    create_process = AsyncMock(side_effect=[VersionProcess(), analysis])
    monkeypatch.setattr(
        "services.native.replaygain_analysis_service.shutil.which",
        lambda _value: "/usr/bin/loudgain",
    )
    monkeypatch.setattr(
        "services.native.replaygain_analysis_service.asyncio.create_subprocess_exec",
        create_process,
    )
    service = ReplayGainAnalysisService()

    task = asyncio.create_task(service.analyze((source,), album_aware=False))
    await started.wait()
    task.cancel()
    await terminated.wait()

    assert service._semaphore.locked()
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert service._semaphore.locked()
    assert not task.done()
    allow_exit.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert analysis.returncode == -15
    assert not service._semaphore.locked()
