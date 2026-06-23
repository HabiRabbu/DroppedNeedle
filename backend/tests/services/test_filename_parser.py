"""Filename/folder parsing fallback (Lidarr-style) for poorly-tagged files."""

from pathlib import Path

import pytest

from services.native.filename_parser import parse_names_from_path


@pytest.mark.parametrize(
    "path,artist,album,title,track,year",
    [
        (
            "/music/Trapeze/Trapeze - Hot Wire/Trapeze - Hot Wire - 05 - Turn It On.mp3",
            "Trapeze",
            "Hot Wire",
            "Turn It On",
            5,
            None,
        ),
        (
            "/music/Blaze Foley/(2010) Sittin' by the Road/04. Blaze Foley - Slow Boat to China.mp3",
            "Blaze Foley",
            "Sittin' by the Road",
            "Slow Boat to China",
            4,
            2010,
        ),
        (
            "/music/MARINA/Electra Heart (2012)/MARINA - Electra Heart - 07 - Power & Control.flac",
            "MARINA",
            "Electra Heart",
            "Power & Control",
            7,
            2012,
        ),
    ],
)
def test_parses_common_layouts(path, artist, album, title, track, year):
    r = parse_names_from_path(Path(path))
    assert r.artist == artist
    assert r.album == album
    assert r.title == title
    assert r.track_number == track
    assert r.year == year


def test_handles_file_with_no_parent_folders():
    r = parse_names_from_path(Path("/lonely.mp3"))
    assert r.title == "lonely"
    assert r.artist is None and r.album is None


def test_strips_artist_prefix_from_album_folder():
    r = parse_names_from_path(Path("/m/Trapeze/Trapeze - Hot Wire/02 - Take It On.mp3"))
    assert r.album == "Hot Wire"
    assert r.title == "Take It On"
    assert r.track_number == 2
