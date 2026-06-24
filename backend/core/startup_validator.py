"""StartupValidator - fail fast on library/staging misconfiguration (basic).

Run from the FastAPI ``lifespan`` startup sequence inside ``asyncio.to_thread()``
(the path checks do blocking ``os.stat``/``os.access`` that must not stall the
event loop on a slow network filesystem). Fatal problems raise
``ConfigurationError`` (a mapped domain exception) so the app refuses to start;
non-fatal ones are logged as warnings.

Paths come from ``PreferencesService.get_library_settings()`` (AUD-2), resolved
by the caller and passed in - the validator itself takes plain paths so it stays
trivially testable. A non-fatal ``fpcalc`` availability check warns when AcoustID
fingerprinting will be unavailable.
"""

import logging
import os
import shutil
from pathlib import Path

from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class StartupValidator:
    def __init__(
        self,
        library_paths: list[Path],
        staging_path: Path | None,
        slskd_downloads_path: Path | None = None,
    ) -> None:
        self._library_paths = library_paths
        self._staging_path = staging_path
        self._slskd_downloads_path = slskd_downloads_path

    def validate(self) -> None:
        """Raise ``ConfigurationError`` on fatal misconfiguration; log warnings
        otherwise. Safe to run in ``asyncio.to_thread()``."""
        errors: list[str] = []
        warnings: list[str] = []

        # Non-fatal: without fpcalc the scanner skips Tier-3 fingerprinting. Queued
        # first so it is still logged on the early-return (broken-library) paths.
        if shutil.which("fpcalc") is None:
            warnings.append(
                "fpcalc binary not found in PATH. AcoustID fingerprinting will be "
                "disabled. Install libchromaprint-tools to enable."
            )

        if not self._library_paths:
            warnings.append("No library paths configured; library features will be empty.")

        for lib_path in self._library_paths:
            if not lib_path.exists():
                errors.append(f"Library path does not exist: {lib_path}")
            elif not os.access(lib_path, os.W_OK):
                # v1: warning only - first-boot Docker volume perms need boot-to-UI.
                warnings.append(f"Library path is not writable: {lib_path}")

        # Don't proceed to staging checks with broken library paths.
        if errors:
            self._finish(errors, warnings)

        if self._staging_path is not None:
            if not self._staging_path.exists():
                try:
                    self._staging_path.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    errors.append(
                        f"Staging directory {self._staging_path} could not be created: {exc}"
                    )
                    self._finish(errors, warnings)

            try:
                staging_dev = self._staging_path.stat().st_dev
                existing_libs = [p for p in self._library_paths if p.exists()]
                same_fs = any(p.stat().st_dev == staging_dev for p in existing_libs)
            except OSError as exc:
                # TOCTOU / broken symlink / network FS hiccup - surface as a clean
                # ConfigurationError rather than a raw traceback.
                errors.append(f"Could not stat staging/library paths: {exc}")
                self._finish(errors, warnings)
            else:
                if existing_libs and not same_fs:
                    errors.append(
                        f"Staging directory {self._staging_path} is not on the same filesystem "
                        f"as any library path. Atomic moves will fail."
                    )

        # C7: the slskd downloads mount must be set, present, writable, and on the
        # same filesystem as the library (the import is an os.rename out of it). A
        # misconfigured mount is an operator-fixable DEPLOYMENT problem, not a reason
        # to refuse boot: warn (download client DEGRADED) and boot to UI. The per-file
        # import path surfaces an actionable failure if the mount is still unavailable.
        warnings.extend(self._check_downloads_mount())

        self._finish(errors, warnings)

    def _check_downloads_mount(self) -> list[str]:
        """One warning per failing condition on the slskd downloads mount (DEGRADED;
        never fatal). Empty list when healthy or unset-and-not-configured."""
        path = self._slskd_downloads_path
        if path is None:
            return ["slskd_downloads_path is not set"]
        if not path.exists():
            return [f"slskd downloads path {path} does not exist"]
        problems: list[str] = []
        if not os.access(path, os.W_OK):
            problems.append(f"slskd downloads path {path} is not writable")
        try:
            dev = path.stat().st_dev
            existing_libs = [p for p in self._library_paths if p.exists()]
            same_fs = any(p.stat().st_dev == dev for p in existing_libs)
        except OSError as exc:
            problems.append(f"could not stat slskd downloads path {path}: {exc}")
            return problems
        if existing_libs and not same_fs:
            problems.append(
                f"slskd downloads path {path} is not on the same filesystem as the "
                f"library (st_dev mismatch); imports fall back to a copy instead of an "
                f"atomic move (slower) but still work"
            )
        return problems

    @staticmethod
    def _finish(errors: list[str], warnings: list[str]) -> None:
        for warning in warnings:
            logger.warning(warning)
        if errors:
            raise ConfigurationError("; ".join(errors))
