"""T1.1 - dual XML/JSON/JSONP subsonic-response serializer."""

import json
import xml.etree.ElementTree as ET

from api.compat.subsonic.models import SArtistID3, SGenre, SIndexID3, SArtistsID3
from api.compat.subsonic.serialization import render, render_error

_NS = "{http://subsonic.org/restapi}"


def _json(resp) -> dict:
    return json.loads(resp.body)["subsonic-response"]


def test_envelope_fields_present_both_formats():
    j = _json(render(None, None, fmt="json"))
    assert j["status"] == "ok"
    assert j["version"] == "1.16.1"
    assert j["type"] == "DroppedNeedle"
    assert "serverVersion" in j
    assert j["openSubsonic"] is True

    xml = render(None, None, fmt="xml").body.decode()
    root = ET.fromstring(xml)
    assert root.tag == f"{_NS}subsonic-response"
    assert root.attrib["status"] == "ok"
    assert root.attrib["version"] == "1.16.1"
    assert root.attrib["type"] == "DroppedNeedle"
    assert root.attrib["openSubsonic"] == "true"


def test_repeatable_element_is_array_even_for_zero_and_one():
    one = SArtistsID3(index=[SIndexID3(name="A", artist=[SArtistID3(id="ar-1", name="A1")])])
    j = _json(render("artists", one, fmt="json"))
    assert isinstance(j["artists"]["index"], list)
    assert isinstance(j["artists"]["index"][0]["artist"], list)
    assert len(j["artists"]["index"][0]["artist"]) == 1

    two = SArtistsID3(index=[SIndexID3(name="A", artist=[
        SArtistID3(id="ar-1", name="A1"), SArtistID3(id="ar-2", name="A2")])])
    j2 = _json(render("artists", two, fmt="json"))
    assert len(j2["artists"]["index"][0]["artist"]) == 2

    empty = SArtistsID3(index=[])
    j3 = _json(render("artists", empty, fmt="json"))
    assert j3["artists"]["index"] == []


def test_element_text_becomes_value_key():
    payload = {"genre": [SGenre(value="Rock", songCount=120, albumCount=12)]}
    j = _json(render("genres", payload, fmt="json"))
    assert j["genres"]["genre"][0] == {"value": "Rock", "songCount": 120, "albumCount": 12}

    xml = render("genres", payload, fmt="xml").body.decode()
    g = ET.fromstring(xml).find(f"{_NS}genres/{_NS}genre")
    assert g.text == "Rock"
    assert g.attrib["songCount"] == "120"
    assert g.attrib["albumCount"] == "12"


def test_booleans_and_numbers_are_real_types():
    payload = {"genre": [SGenre(value="Rock", songCount=120, albumCount=12)]}
    j = _json(render("genres", payload, fmt="json"))
    assert j["openSubsonic"] is True
    assert isinstance(j["genres"]["genre"][0]["songCount"], int)
    assert not isinstance(j["genres"]["genre"][0]["songCount"], bool)


def test_json_success_and_failed_shapes():
    ok = _json(render(None, None, fmt="json"))
    assert "error" not in ok
    failed_resp = render_error(40, "Wrong username or password", fmt="json")
    f = _json(failed_resp)
    assert f["status"] == "failed"
    assert f["error"] == {"code": 40, "message": "Wrong username or password"}
    assert failed_resp.status_code == 200  # non-binary failures are HTTP 200


def test_xml_error_shape():
    xml = render_error(70, "not found", fmt="xml").body.decode()
    root = ET.fromstring(xml)
    assert root.attrib["status"] == "failed"
    err = root.find(f"{_NS}error")
    assert err.attrib["code"] == "70"
    assert err.attrib["message"] == "not found"


def test_jsonp_wraps_callback():
    resp = render(None, None, fmt="jsonp", callback="cb")
    body = resp.body.decode()
    assert body.startswith("cb(") and body.endswith(");")
    assert resp.media_type == "application/javascript"
    inner = json.loads(body[3:-2])
    assert inner["subsonic-response"]["status"] == "ok"


def test_none_fields_are_stripped():
    # SArtistID3 with no album -> album key omitted (not null)
    j = _json(render("artist", SArtistID3(id="ar-1", name="A1"), fmt="json"))
    assert "album" not in j["artist"]
    assert "starred" not in j["artist"]


def test_jsonp_rejects_non_identifier_callback_no_xss():
    # A non-identifier callback must NOT be reflected into a JS response (XSS); fall
    # back to plain JSON instead.
    resp = render(None, None, fmt="jsonp", callback="</script><script>alert(1)//")
    assert resp.media_type == "application/json"
    assert b"<script>" not in resp.body
    # the rate-limit / error path uses the same emitter
    err = render_error(0, "x", fmt="jsonp", callback="a()=>b")
    assert err.media_type == "application/json"


def test_xml_strips_illegal_control_chars():
    # Control bytes from file metadata would make the whole document unparseable;
    # they must be stripped so strict XML clients can still read the response.
    a = SArtistsID3(index=[SIndexID3(
        name="A", artist=[SArtistID3(id="ar-1", name="Bad\x00\x08Name")])])
    xml = render("artists", a, fmt="xml").body.decode()
    ET.fromstring(xml)  # must not raise
    assert "\x00" not in xml and "\x08" not in xml
    assert "BadName" in xml
