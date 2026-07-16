import json

import pytest

from api.compat.subsonic.ids import encode
from tests.compat.conftest import subsonic_query


def _body(response):
    return json.loads(response.content)["subsonic-response"]


@pytest.mark.asyncio
async def test_legacy_and_index_queue_preserve_order_duplicates_and_position(compat_env):
    first, second = [encode("track", item) for item in compat_env.ids["tracks"]]
    query = subsonic_query(compat_env.secret, "alice")
    save = compat_env.client.post(
        "/subsonic/rest/savePlayQueue",
        params=[*query.items(), ("id", first), ("id", second), ("id", first),
                ("current", first), ("position", "1234")],
    )
    assert _body(save)["status"] == "ok"

    legacy = _body(
        compat_env.client.get("/subsonic/rest/getPlayQueue", params=query)
    )["playQueue"]
    assert [item["id"] for item in legacy["entry"]] == [first, second, first]
    assert legacy["current"] == first
    assert legacy["position"] == 1234

    indexed = _body(
        compat_env.client.get("/subsonic/rest/getPlayQueueByIndex", params=query)
    )["playQueueByIndex"]
    assert indexed["currentIndex"] == 0


@pytest.mark.asyncio
async def test_index_queue_supports_second_duplicate_and_validates_atomically(compat_env):
    first = encode("track", compat_env.ids["tracks"][0])
    query = subsonic_query(compat_env.secret, "alice")
    valid = [*query.items(), ("id", first), ("id", first),
             ("currentIndex", "1"), ("position", "42")]
    assert _body(
        compat_env.client.post("/subsonic/rest/savePlayQueueByIndex", params=valid)
    )["status"] == "ok"

    invalid = [*query.items(), ("id", first), ("currentIndex", "3")]
    assert _body(
        compat_env.client.post("/subsonic/rest/savePlayQueueByIndex", params=invalid)
    )["status"] == "failed"
    current = _body(
        compat_env.client.get("/subsonic/rest/getPlayQueueByIndex", params=query)
    )["playQueueByIndex"]
    assert current["currentIndex"] == 1
    assert len(current["entry"]) == 2


@pytest.mark.asyncio
async def test_queue_and_bookmarks_are_isolated_between_users(compat_env):
    track_id = encode("track", compat_env.ids["tracks"][0])
    alice = subsonic_query(compat_env.secret, "alice")
    _record, bob_secret = await compat_env.app_passwords.create(
        "user-bob", "bob playback"
    )
    bob = subsonic_query(bob_secret, "bob")

    assert _body(compat_env.client.post(
        "/subsonic/rest/savePlayQueue",
        params=[*alice.items(), ("id", track_id), ("current", track_id)],
    ))["status"] == "ok"
    assert _body(compat_env.client.post(
        "/subsonic/rest/createBookmark",
        params=[*alice.items(), ("id", track_id), ("position", "9000"),
                ("comment", "private")],
    ))["status"] == "ok"

    assert _body(
        compat_env.client.get("/subsonic/rest/getPlayQueue", params=bob)
    )["playQueue"]["entry"] == []
    assert _body(
        compat_env.client.get("/subsonic/rest/getBookmarks", params=bob)
    )["bookmarks"]["bookmark"] == []
    bookmark = _body(
        compat_env.client.get("/subsonic/rest/getBookmarks", params=alice)
    )["bookmarks"]["bookmark"][0]
    assert bookmark["position"] == 9000
    assert bookmark["comment"] == "private"


@pytest.mark.asyncio
async def test_bookmark_missing_target_and_delete_are_protocol_safe(compat_env):
    query = subsonic_query(compat_env.secret, "alice")
    missing = encode("track", "missing")
    failed = _body(compat_env.client.post(
        "/subsonic/rest/createBookmark",
        params=[*query.items(), ("id", missing), ("position", "1")],
    ))
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == 70

    track_id = encode("track", compat_env.ids["tracks"][0])
    params = [*query.items(), ("id", track_id)]
    assert _body(compat_env.client.post(
        "/subsonic/rest/deleteBookmark", params=params
    ))["status"] == "ok"
