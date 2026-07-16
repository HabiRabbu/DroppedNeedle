import json

import pytest

from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


@pytest.mark.asyncio
async def test_scan_status_is_available_to_authenticated_users(compat_env):
    compat_env.scan.status.return_value = (True, 37)
    body = _body(compat_env.client.get(
        "/subsonic/rest/getScanStatus",
        params=subsonic_query(compat_env.secret, "alice"),
    ))

    assert body["scanStatus"] == {"scanning": True, "count": 37}


@pytest.mark.asyncio
async def test_scan_start_is_admin_only(compat_env):
    body = _body(compat_env.client.post(
        "/subsonic/rest/startScan",
        params=subsonic_query(compat_env.secret, "alice"),
    ))

    assert body["status"] == "failed"
    assert body["error"]["code"] == 50
    compat_env.scan.start.assert_not_awaited()

    await compat_env.auth_store.update_user_role("user-bob", "admin")
    _record, secret = await compat_env.app_passwords.create("user-bob", "admin scan")
    allowed = _body(compat_env.client.post(
        "/subsonic/rest/startScan",
        params=subsonic_query(secret, "bob"),
    ))
    assert allowed["scanStatus"] == {"scanning": True, "count": 0}
    compat_env.scan.start.assert_awaited_once()
