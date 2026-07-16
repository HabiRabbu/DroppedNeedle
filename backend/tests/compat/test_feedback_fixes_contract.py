import hashlib
import json
from pathlib import Path

import pytest

from api.compat.subsonic.ids import decode, encode

_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "feedback_fixes"
    / "compat_contract_v1.json"
)


def _jellyfin_id(kind: str, internal_id: str) -> str:
    return hashlib.sha256(f"{kind}:{internal_id}".encode()).hexdigest()[:32]


def test_feedback_fixes_contract_pins_every_emitted_id_form() -> None:
    contract = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    identified = contract["identified"]

    for kind in ("album", "artist", "track"):
        native = identified["native"][f"{kind}_id"]
        subsonic = identified["subsonic"][f"{kind}_id"]
        jellyfin = identified["jellyfin"][f"{kind}_id"]
        assert encode(kind, native) == subsonic
        assert decode(subsonic) == (kind, native)
        assert _jellyfin_id(kind, native) == jellyfin

    playlist = contract["playlist"]
    assert encode("playlist", playlist["native_id"]) == playlist["subsonic_id"]
    assert _jellyfin_id("playlist", playlist["native_id"]) == playlist["jellyfin_id"]
    assert contract["review_only"]["subsonic"] is None
    assert contract["review_only"]["jellyfin"] is None


@pytest.mark.asyncio
async def test_feedback_fixes_contract_round_trips_persisted_jellyfin_ids(
    compat_id_map_service,
) -> None:
    contract = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    for kind in ("album", "artist", "track"):
        internal = contract["identified"]["native"][f"{kind}_id"]
        expected = contract["identified"]["jellyfin"][f"{kind}_id"]
        assert await compat_id_map_service.to_jf(kind, internal) == expected
        assert await compat_id_map_service.from_jf(expected) == (kind, internal)
