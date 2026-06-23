"""T0.5 - CompatIdMapService: round-trip, stability, dash-normalization."""

import re

import pytest

from core.exceptions import JellyfinError

pytestmark = pytest.mark.asyncio

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


async def test_round_trip_all_kinds(compat_id_map_service):
    cases = [
        ("artist", "a74b1b7f-71a5-4011-9441-d0b5e4122711"),
        ("album", "b1392450-e666-3926-a536-22c65f834433"),
        ("track", "9f8c1234567890abcdef1234567890ab"),
        ("playlist", "pl-uuid-1234"),
        ("genre", "electronic"),
    ]
    for kind, internal in cases:
        jf = await compat_id_map_service.to_jf(kind, internal)
        assert _HEX32.match(jf), f"{kind} jf id not 32-hex: {jf}"
        assert await compat_id_map_service.from_jf(jf) == (kind, internal)


async def test_same_input_same_id_across_calls(compat_id_map_service):
    a = await compat_id_map_service.to_jf("track", "file-1")
    b = await compat_id_map_service.to_jf("track", "file-1")
    assert a == b


async def test_distinct_inputs_distinct_ids(compat_id_map_service):
    a = await compat_id_map_service.to_jf("track", "file-1")
    b = await compat_id_map_service.to_jf("album", "file-1")
    c = await compat_id_map_service.to_jf("track", "file-2")
    assert len({a, b, c}) == 3


async def test_dashed_input_normalizes_to_same_row(compat_id_map_service):
    jf = await compat_id_map_service.to_jf("artist", "some-artist-mbid")
    # client re-formats the 32-hex as a dashed GUID 8-4-4-4-12
    dashed = f"{jf[:8]}-{jf[8:12]}-{jf[12:16]}-{jf[16:20]}-{jf[20:]}"
    assert await compat_id_map_service.from_jf(dashed) == ("artist", "some-artist-mbid")
    # uppercase also normalizes
    assert await compat_id_map_service.from_jf(jf.upper()) == ("artist", "some-artist-mbid")


async def test_unknown_id_raises_jellyfin_404(compat_id_map_service):
    with pytest.raises(JellyfinError) as e:
        await compat_id_map_service.from_jf("0" * 32)
    assert e.value.status == 404


async def test_invalid_kind_raises(compat_id_map_service):
    with pytest.raises(ValueError):
        await compat_id_map_service.to_jf("bogus", "x")
