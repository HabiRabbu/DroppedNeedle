"""Read-only helpers for determining Linux rename boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_MOUNT_ESCAPES = {
    r"\040": " ",
    r"\011": "\t",
    r"\012": "\n",
    r"\134": "\\",
}


@dataclass(frozen=True)
class MoveBoundary:
    move_supported: bool
    reason: str


def _unescape_mount_path(value: str) -> str:
    for escaped, decoded in _MOUNT_ESCAPES.items():
        value = value.replace(escaped, decoded)
    return value


def parse_mountinfo(content: str) -> list[tuple[int, Path]]:
    mounts: list[tuple[int, Path]] = []
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 6 or "-" not in fields:
            continue
        try:
            mount_id = int(fields[0])
        except ValueError:
            continue
        mounts.append((mount_id, Path(_unescape_mount_path(fields[4]))))
    return mounts


def _containing_mount_id(path: Path, mounts: list[tuple[int, Path]]) -> int | None:
    resolved = path.resolve(strict=False)
    matches = [
        (len(mount.parts), mount_id)
        for mount_id, mount in mounts
        if resolved == mount or mount in resolved.parents
    ]
    return max(matches, default=(0, None))[1]


def check_move_boundary(
    source: Path,
    destination: Path,
    *,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
) -> MoveBoundary:
    """Return whether ``os.replace`` should cross a Linux mount boundary.

    Mount IDs are authoritative when mountinfo is readable. ``st_dev`` is the
    portable fallback; the real replace operation remains the final authority.
    """
    try:
        mounts = parse_mountinfo(mountinfo_path.read_text())
    except OSError:
        mounts = []
    if mounts:
        source_mount = _containing_mount_id(source, mounts)
        destination_mount = _containing_mount_id(destination, mounts)
        if source_mount is not None and destination_mount is not None:
            if source_mount == destination_mount:
                return MoveBoundary(True, "common_mount")
            return MoveBoundary(False, "different_mount")
    try:
        same_device = source.stat().st_dev == destination.stat().st_dev
    except OSError:
        return MoveBoundary(False, "stat_error")
    return MoveBoundary(
        same_device,
        "common_filesystem" if same_device else "different_filesystem",
    )
