from __future__ import annotations

from pathlib import Path

from infrastructure.filesystem_mounts import check_move_boundary, parse_mountinfo


def _mount_line(mount_id: int, parent_id: int, mount_point: str) -> str:
    return f"{mount_id} {parent_id} 0:1 / {mount_point} rw - ext4 /dev/test rw"


def test_common_parent_mount_supports_fast_move(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(_mount_line(10, 1, "/data"))

    result = check_move_boundary(
        Path("/data/slsk/album"),
        Path("/data/music"),
        mountinfo_path=mountinfo,
    )

    assert result.move_supported is True
    assert result.reason == "common_mount"


def test_sibling_and_nested_bind_mounts_are_separate(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "\n".join(
            [
                _mount_line(10, 1, "/data"),
                _mount_line(11, 10, "/data/slsk"),
                _mount_line(12, 10, "/data/music"),
                _mount_line(13, 12, "/data/music/special"),
            ]
        )
    )

    siblings = check_move_boundary(
        Path("/data/slsk/album"), Path("/data/music"), mountinfo_path=mountinfo
    )
    nested = check_move_boundary(
        Path("/data/music/album"),
        Path("/data/music/special/album"),
        mountinfo_path=mountinfo,
    )

    assert siblings.reason == "different_mount"
    assert nested.reason == "different_mount"


def test_mountinfo_parser_decodes_escaped_paths() -> None:
    mounts = parse_mountinfo(_mount_line(42, 1, r"/media/Music\040Library"))

    assert mounts == [(42, Path("/media/Music Library"))]


def test_missing_mountinfo_falls_back_to_device_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    result = check_move_boundary(
        source,
        destination,
        mountinfo_path=tmp_path / "missing-mountinfo",
    )

    assert result.move_supported is True
    assert result.reason == "common_filesystem"
