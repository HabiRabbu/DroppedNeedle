"""Bounded analysis-only loudgain integration for Library Management."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import math
from pathlib import Path
import shutil
import subprocess

from models.library_management_enrichment import (
    ReplayGainAnalysis,
    ReplayGainTrackResult,
)

_MAX_ALBUM_TRACKS = 500
_MAX_ANALYSIS_SECONDS = 300

ReplayGainRunner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def _number(value: str, suffix: str = "") -> float:
    normalized = value.removesuffix(suffix).strip()
    result = float(normalized)
    if not math.isfinite(result):
        raise ValueError("loudgain returned a non-finite value")
    return result


def _file_state(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class ReplayGainAnalysisService:
    def __init__(
        self,
        executable: str = "loudgain",
        *,
        runner: ReplayGainRunner | None = None,
    ) -> None:
        self._executable = executable
        self._runner = runner
        self._runner_injected = runner is not None
        self._semaphore = asyncio.Semaphore(1)
        self._version: str | None = None

    async def analyze(
        self,
        paths: Sequence[Path],
        *,
        album_aware: bool,
    ) -> ReplayGainAnalysis:
        sources = tuple(paths)
        if not sources or len(sources) > _MAX_ALBUM_TRACKS:
            return ReplayGainAnalysis(
                status="deferred", reason="The ReplayGain album size is invalid."
            )
        if len(set(sources)) != len(sources) or any(
            not path.is_absolute() or "\t" in str(path) or "\n" in str(path)
            for path in sources
        ):
            return ReplayGainAnalysis(
                status="deferred", reason="A ReplayGain source path is invalid."
            )
        executable = (
            self._executable
            if self._runner_injected
            else shutil.which(self._executable)
        )
        if executable is None:
            return ReplayGainAnalysis(
                status="deferred", reason="The loudgain analyzer is unavailable."
            )
        try:
            before = tuple(_file_state(path) for path in sources)
        except OSError:
            return ReplayGainAnalysis(
                status="deferred", reason="A ReplayGain source is unavailable."
            )
        timeout = min(_MAX_ANALYSIS_SECONDS, 30 + 10 * len(sources))
        command = (
            executable,
            "-a" if album_aware else "-r",
            "-s",
            "s",
            "-O",
            "-q",
            *(str(path) for path in sources),
        )
        async with self._semaphore:
            try:
                if self._version is None:
                    version = await self._run_command((executable, "--version"), 10)
                    if version.returncode == 0:
                        self._version = (
                            version.stdout.strip() or version.stderr.strip() or None
                        )
                completed = await self._run_command(command, timeout)
            except (OSError, subprocess.SubprocessError, ValueError):
                return ReplayGainAnalysis(
                    status="deferred",
                    analyzer_version=self._version,
                    reason="ReplayGain analysis failed.",
                )
        if completed.returncode != 0:
            return ReplayGainAnalysis(
                status="deferred",
                analyzer_version=self._version,
                reason="ReplayGain analysis failed.",
            )
        try:
            after = tuple(_file_state(path) for path in sources)
        except OSError:
            return ReplayGainAnalysis(
                status="deferred",
                analyzer_version=self._version,
                reason="A ReplayGain source changed during analysis.",
            )
        if after != before:
            return ReplayGainAnalysis(
                status="deferred",
                analyzer_version=self._version,
                reason="The analyzer changed a source file.",
            )
        try:
            tracks = self._parse_output(
                completed.stdout,
                sources=sources,
                album_aware=album_aware,
            )
        except (KeyError, ValueError):
            return ReplayGainAnalysis(
                status="deferred",
                analyzer_version=self._version,
                reason="ReplayGain returned an invalid result.",
            )
        return ReplayGainAnalysis(
            status="available",
            tracks=tracks,
            analyzer_version=self._version,
        )

    async def _run_command(
        self, command: Sequence[str], timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]:
        if self._runner is not None:
            return await asyncio.to_thread(self._runner, command, timeout_seconds)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.CancelledError:
            await self._finish_process_cleanup(process)
            raise
        except TimeoutError as error:
            await self._finish_process_cleanup(process)
            raise subprocess.TimeoutExpired(command, timeout_seconds) from error
        assert process.returncode is not None
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    @classmethod
    async def _finish_process_cleanup(cls, process: asyncio.subprocess.Process) -> None:
        cleanup = asyncio.create_task(cls._terminate_process(process))
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    def _parse_output(
        output: str,
        *,
        sources: tuple[Path, ...],
        album_aware: bool,
    ) -> tuple[ReplayGainTrackResult, ...]:
        lines = [line for line in output.splitlines() if line]
        header_index = next(
            (index for index, line in enumerate(lines) if line.startswith("File\t")),
            None,
        )
        if header_index is None:
            raise ValueError("loudgain did not return a header")
        headers = lines[header_index].split("\t")
        gain_index = headers.index("Gain")
        peak_index = headers.index("True_Peak")
        by_path: dict[str, tuple[float, float]] = {}
        album: tuple[float, float] | None = None
        for line in lines[header_index + 1 :]:
            columns = line.split("\t")
            if len(columns) != len(headers):
                raise ValueError("unexpected loudgain column count")
            gain = _number(columns[gain_index], "dB")
            peak = _number(columns[peak_index])
            if peak < 0:
                raise ValueError("negative ReplayGain peak")
            if columns[0] == "Album":
                album = (gain, peak)
            else:
                by_path[columns[0]] = (gain, peak)
        if set(by_path) != {str(path) for path in sources}:
            raise ValueError("loudgain did not return every source")
        if album_aware and album is None:
            raise ValueError("loudgain did not return album values")
        return tuple(
            ReplayGainTrackResult(
                source_path=str(path),
                track_gain_db=by_path[str(path)][0],
                track_peak=by_path[str(path)][1],
                album_gain_db=album[0] if album is not None else None,
                album_peak=album[1] if album is not None else None,
            )
            for path in sources
        )
