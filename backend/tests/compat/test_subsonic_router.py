"""T1.2 - Subsonic ids + auth + router skeleton (ping, extensions, boundary)."""

import json

import pytest

from api.compat.subsonic.ids import decode, encode
from core.exceptions import SubsonicError

_aio = pytest.mark.asyncio


def _sub(resp):
    return json.loads(resp.content)["subsonic-response"]


# ----- ids (pure, sync) -----

def test_id_roundtrip_all_kinds():
    for kind, internal in [
        ("artist", "a74b1b7f-71a5-4011-9441-d0b5e4122711"),
        ("album", "b1392450-e666-3926-a536-22c65f834433"),
        ("track", "9f8c"), ("playlist", "pl-uuid"), ("genre", "electronic"),
    ]:
        sid = encode(kind, internal)
        assert decode(sid) == (kind, internal)


def test_decode_unknown_prefix_is_70():
    with pytest.raises(SubsonicError) as e:
        decode("zz-bogus")
    assert e.value.code == 70


# ----- ping (both path forms) -----

@_aio
async def test_ping_ok_both_forms(compat_env):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret}
    for path in ("/subsonic/rest/ping", "/subsonic/rest/ping.view"):
        r = compat_env.client.get(path, params=q)
        assert r.status_code == 200
        assert _sub(r)["status"] == "ok"


@_aio
async def test_ping_token_scheme(compat_env):
    from tests.compat.conftest import subsonic_query

    q = subsonic_query(compat_env.secret, "alice", scheme="token")
    r = compat_env.client.get("/subsonic/rest/ping", params=q)
    assert _sub(r)["status"] == "ok"


@_aio
async def test_ping_bad_password_is_40(compat_env):
    from tests.compat.conftest import subsonic_query

    q = subsonic_query("wrong-secret", "alice", scheme="enc")
    r = compat_env.client.get("/subsonic/rest/ping", params=q)
    body = _sub(r)
    assert r.status_code == 200  # non-binary failure stays HTTP 200
    assert body["status"] == "failed"
    assert body["error"]["code"] == 40


@_aio
async def test_ping_missing_auth_fails(compat_env):
    r = compat_env.client.get("/subsonic/rest/ping", params={"f": "json"})
    body = _sub(r)
    assert body["status"] == "failed"
    assert body["error"]["code"] in (10, 40)


# ----- public extensions endpoint (no auth) -----

@_aio
async def test_extensions_public_no_auth(compat_env):
    r = compat_env.client.get("/subsonic/rest/getOpenSubsonicExtensions", params={"f": "json"})
    body = _sub(r)
    assert body["status"] == "ok"
    names = {e["name"] for e in body["openSubsonicExtensions"]}
    assert "apiKeyAuthentication" in names
    assert "formPost" in names


# ----- enablement -----

@_aio
async def test_disabled_protocol_fails(compat_env):
    from api.v1.schemas.settings import ConnectAppsSettings

    compat_env.preferences.save_connect_apps_settings(
        ConnectAppsSettings(subsonic_enabled=False)
    )
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret}
    r = compat_env.client.get("/subsonic/rest/ping", params=q)
    assert _sub(r)["status"] == "failed"


# ----- error boundary: never the native envelope -----

@_aio
async def test_unknown_method_renders_subsonic_envelope(compat_env):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret}
    r = compat_env.client.get("/subsonic/rest/bogusMethod", params=q)
    body = json.loads(r.content)
    assert "subsonic-response" in body  # NOT the native {"error":{...}} shape
    assert body["subsonic-response"]["status"] == "failed"


# ----- formPost extension -----

@_aio
async def test_form_post_auth(compat_env):
    r = compat_env.client.post(
        "/subsonic/rest/ping",
        data={"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": compat_env.secret},
    )
    assert _sub(r)["status"] == "ok"
