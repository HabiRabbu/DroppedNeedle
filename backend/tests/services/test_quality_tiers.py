"""Unit tests for the audio quality tier helpers."""

from repositories.protocols.download_client import DownloadSearchResult
from services.native.quality_tiers import (
    candidate_tier,
    file_tier,
    in_range,
    is_flac_or_mp3,
    tier_rank,
)


def _f(filename: str, *, ext: str = "", bitrate: int | None = None) -> DownloadSearchResult:
    return DownloadSearchResult(
        username="u",
        filename=filename,
        parent_directory="p",
        size=1,
        extension=ext,
        bitrate=bitrate,
    )


def test_file_tier_lossless_by_extension():
    assert file_tier(_f("a.flac")) == "lossless"
    assert file_tier(_f("a", ext="flac")) == "lossless"  # extension field wins
    assert file_tier(_f("a.alac")) == "lossless"


def test_file_tier_lossy_bitrate_bands():
    assert file_tier(_f("a.mp3", bitrate=320)) == "mp3_320"
    assert file_tier(_f("a.mp3", bitrate=256)) == "mp3_256"
    assert file_tier(_f("a.mp3", bitrate=192)) == "mp3_192"
    assert file_tier(_f("a.mp3", bitrate=128)) == "low"
    assert file_tier(_f("a.mp3", bitrate=None)) == "low"


def test_file_tier_codec_agnostic_for_lossy():
    # m4a / opus / ogg map onto the same bitrate bands as mp3
    assert file_tier(_f("a.m4a", bitrate=320)) == "mp3_320"
    assert file_tier(_f("a.opus", bitrate=256)) == "mp3_256"
    assert file_tier(_f("a.ogg", bitrate=192)) == "mp3_192"


def test_candidate_tier_is_worst_file():
    assert candidate_tier([_f("a.flac"), _f("b.mp3", bitrate=320)]) == "mp3_320"
    assert candidate_tier([]) == "low"


def test_in_range_inclusive():
    assert in_range("mp3_320", "mp3_320", "lossless")
    assert in_range("lossless", "mp3_320", "lossless")
    assert not in_range("mp3_192", "mp3_320", "lossless")
    assert not in_range("mp3_320", "lossless", "lossless")  # only-lossless excludes mp3


def test_is_flac_or_mp3():
    assert is_flac_or_mp3(_f("a.flac"))
    assert is_flac_or_mp3(_f("a.mp3"))
    assert not is_flac_or_mp3(_f("a.ogg"))
    assert not is_flac_or_mp3(_f("a.m4a"))
    assert not is_flac_or_mp3(_f("a.alac"))  # lossless, but not FLAC/MP3


def test_tier_rank_order():
    assert tier_rank("lossless") > tier_rank("mp3_320") > tier_rank("mp3_192") > tier_rank("low")
