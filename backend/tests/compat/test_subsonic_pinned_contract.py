"""Pinned OpenSubsonic e184c37 wire-contract checks for new capabilities."""

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from api.compat.subsonic.ids import encode
from api.v1.schemas.settings import ConnectAppsSettings
from services.compat.native_lyrics_service import NativeLyrics, NativeLyricsLine
from tests.compat.conftest import subsonic_query

_NS = {"s": "http://subsonic.org/restapi"}
_CONTRACT_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "opensubsonic"
    / "e184c37c3485"
    / "contract.json"
)


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text())


def _json_body(response) -> dict:
    return response.json()["subsonic-response"]


def _xml_root(response):
    assert response.headers["content-type"].startswith("application/xml")
    return ElementTree.fromstring(response.content)


def _xml_query(secret: str, username: str) -> dict[str, str]:
    return {**subsonic_query(secret, username), "f": "xml"}


def test_minimal_contract_snapshot_is_pinned_and_attributed():
    contract = _contract()
    assert contract["upstream_commit"] == (
        "e184c37c3485cdb6afa57ae86b89c9d99e2f1105"
    )
    assert set(contract["extensions"]) == {
        "songLyrics",
        "playbackReport",
        "indexBasedQueue",
        "transcoding",
    }
    assert contract["extensions"]["songLyrics"]["versions"] == [1]


@pytest.mark.asyncio
async def test_song_lyrics_v1_json_and_xml_match_pinned_required_fields(compat_env):
    compat_env.lyrics.get.return_value = NativeLyrics(
        "eng",
        True,
        (NativeLyricsLine("first", 100), NativeLyricsLine("second", 250)),
        "sidecar",
    )
    track_id = encode("track", compat_env.ids["tracks"][0])
    json_response = compat_env.client.get(
        "/subsonic/rest/getLyricsBySongId",
        params={
            **subsonic_query(compat_env.secret, "alice"),
            "id": track_id,
        },
    )
    structured = _json_body(json_response)["lyricsList"]["structuredLyrics"][0]
    required = _contract()["extensions"]["songLyrics"]["required"]
    assert set(required) <= set(structured)
    assert all("value" in line for line in structured["line"])

    xml_response = compat_env.client.get(
        "/subsonic/rest/GETLYRICSBYSONGID.VIEW",
        params={**_xml_query(compat_env.secret, "alice"), "id": track_id},
    )
    root = _xml_root(xml_response)
    lyrics = root.find("s:lyricsList/s:structuredLyrics", _NS)
    assert lyrics is not None
    assert lyrics.attrib["lang"] == "eng"
    assert lyrics.attrib["synced"] == "true"
    assert [line.text for line in lyrics.findall("s:line", _NS)] == [
        "first",
        "second",
    ]


@pytest.mark.asyncio
async def test_index_queue_and_bookmark_json_xml_match_pinned_fields(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    query = subsonic_query(compat_env.secret, "alice")
    compat_env.client.post(
        "/subsonic/rest/savePlayQueueByIndex",
        params=[
            *query.items(),
            ("id", track_id),
            ("currentIndex", "0"),
            ("position", "321"),
        ],
    )
    compat_env.client.post(
        "/subsonic/rest/createBookmark",
        params=[
            *query.items(),
            ("id", track_id),
            ("position", "654"),
        ],
    )

    queue = _json_body(
        compat_env.client.get("/subsonic/rest/getPlayQueueByIndex", params=query)
    )["playQueueByIndex"]
    assert set(_contract()["extensions"]["indexBasedQueue"]["required"]) <= set(
        queue
    )
    assert queue["currentIndex"] == 0

    queue_root = _xml_root(
        compat_env.client.get(
            "/subsonic/rest/getPlayQueueByIndex.view",
            params=_xml_query(compat_env.secret, "alice"),
        )
    )
    queue_xml = queue_root.find("s:playQueueByIndex", _NS)
    assert queue_xml is not None
    assert queue_xml.attrib["username"] == "alice"
    assert queue_xml.attrib["currentIndex"] == "0"
    assert len(queue_xml.findall("s:entry", _NS)) == 1

    bookmarks = _json_body(
        compat_env.client.get("/subsonic/rest/getBookmarks", params=query)
    )["bookmarks"]["bookmark"]
    assert set(_contract()["bookmark_required"]) <= set(bookmarks[0])

    bookmark_root = _xml_root(
        compat_env.client.get(
            "/subsonic/rest/getBookmarks",
            params=_xml_query(compat_env.secret, "alice"),
        )
    )
    bookmark = bookmark_root.find("s:bookmarks/s:bookmark", _NS)
    assert bookmark is not None
    assert bookmark.attrib["position"] == "654"
    assert bookmark.find("s:entry", _NS) is not None


@pytest.mark.asyncio
async def test_playback_report_and_scan_json_xml_contracts(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    report = {
        "mediaId": track_id,
        "mediaType": "song",
        "positionMs": "10",
        "state": "starting",
    }
    json_response = compat_env.client.post(
        "/subsonic/rest/reportPlayback",
        params=subsonic_query(compat_env.secret, "alice"),
        data=report,
    )
    assert _json_body(json_response)["status"] == "ok"

    xml_response = compat_env.client.post(
        "/subsonic/rest/REPORTPLAYBACK.VIEW",
        params=_xml_query(compat_env.secret, "alice"),
        data={**report, "state": "stopped"},
    )
    assert _xml_root(xml_response).attrib["status"] == "ok"

    compat_env.scan.status.return_value = (True, 7)
    scan_json = _json_body(
        compat_env.client.get(
            "/subsonic/rest/getScanStatus",
            params=subsonic_query(compat_env.secret, "alice"),
        )
    )["scanStatus"]
    assert set(_contract()["scan_status_required"]) <= set(scan_json)
    scan_root = _xml_root(
        compat_env.client.get(
            "/subsonic/rest/getScanStatus.view",
            params=_xml_query(compat_env.secret, "alice"),
        )
    )
    scan = scan_root.find("s:scanStatus", _NS)
    assert scan is not None
    assert scan.attrib == {"scanning": "true", "count": "7"}


@pytest.mark.asyncio
async def test_transcode_decision_json_and_xml_match_pinned_contract(
    compat_env, monkeypatch
):
    monkeypatch.setattr(
        "services.compat.advanced_transcode_service.ffmpeg_available", lambda: True
    )
    compat_env.preferences.save_connect_apps_settings(
        ConnectAppsSettings(
            subsonic_enabled=True,
            jellyfin_enabled=True,
            transcoding_enabled=True,
        )
    )
    media = {
        "mediaId": encode("track", compat_env.ids["tracks"][0]),
        "mediaType": "song",
    }
    client_info = {
        "name": "contract test",
        "platform": "pytest",
        "directPlayProfiles": [
            {
                "containers": ["flac"],
                "audioCodecs": ["flac"],
                "protocols": ["http"],
            }
        ],
    }
    json_response = compat_env.client.post(
        "/subsonic/rest/getTranscodeDecision",
        params={**subsonic_query(compat_env.secret, "alice"), **media},
        json=client_info,
    )
    decision = _json_body(json_response)["transcodeDecision"]
    required = _contract()["extensions"]["transcoding"]["required"]
    assert set(required) <= set(decision)

    xml_response = compat_env.client.post(
        "/subsonic/rest/GETTRANSCODEDECISION.VIEW",
        params={**_xml_query(compat_env.secret, "alice"), **media},
        json=client_info,
    )
    transcode = _xml_root(xml_response).find("s:transcodeDecision", _NS)
    assert transcode is not None
    assert {"canDirectPlay", "canTranscode"} <= set(transcode.attrib)
    assert transcode.find("s:sourceStream", _NS) is not None
