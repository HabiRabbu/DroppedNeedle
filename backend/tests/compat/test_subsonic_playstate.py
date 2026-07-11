"""Subsonic play-state endpoints: savePlayQueue/getPlayQueue + bookmarks."""

import json

import pytest

pytestmark = pytest.mark.asyncio


def _sub(resp):
    assert resp.status_code == 200
    return json.loads(resp.content)["subsonic-response"]


def _get(env, endpoint, params=None, **extra):
    q = {"v": "1.16.1", "c": "pytest", "f": "json", "apiKey": env.secret, **extra}
    return env.client.get(f"/subsonic/rest/{endpoint}", params={**q, **(params or {})})


def _track_ids(env):
    return [f"tr-{fid}" for fid in env.ids["tracks"]]


# ----- play queue -----


async def test_play_queue_round_trip(compat_env):
    t1, t2 = _track_ids(compat_env)
    save = compat_env.client.get(
        "/subsonic/rest/savePlayQueue",
        params=[
            ("v", "1.16.1"), ("c", "symfonium"), ("f", "json"),
            ("apiKey", compat_env.secret),
            ("id", t1), ("id", t2), ("current", t2), ("position", "31500"),
        ],
    )
    assert _sub(save)["status"] == "ok"

    body = _sub(_get(compat_env, "getPlayQueue"))
    q = body["playQueue"]
    assert q["current"] == t2
    assert q["position"] == 31500
    assert q["username"] == "alice"
    assert q["changedBy"] == "symfonium"
    assert [e["id"] for e in q["entry"]] == [t1, t2]


async def test_get_play_queue_empty_is_bare_ok(compat_env):
    body = _sub(_get(compat_env, "getPlayQueue"))
    assert body["status"] == "ok"
    assert "playQueue" not in body


async def test_save_play_queue_no_ids_clears(compat_env):
    t1, _ = _track_ids(compat_env)
    _sub(_get(compat_env, "savePlayQueue", id=t1, current=t1, position="5"))
    _sub(_get(compat_env, "savePlayQueue"))
    body = _sub(_get(compat_env, "getPlayQueue"))
    assert "playQueue" not in body


async def test_play_queue_xml_envelope(compat_env):
    t1, _ = _track_ids(compat_env)
    _sub(_get(compat_env, "savePlayQueue", id=t1, current=t1, position="1000"))
    q = {"v": "1.16.1", "c": "pytest", "apiKey": compat_env.secret}
    r = compat_env.client.get("/subsonic/rest/getPlayQueue", params=q)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    text = r.content.decode()
    assert 'status="ok"' in text
    assert "<playQueue" in text and "<entry" in text


async def test_play_queue_requires_auth(compat_env):
    r = compat_env.client.get("/subsonic/rest/getPlayQueue", params={"f": "json"})
    body = json.loads(r.content)["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] in (10, 40)


# ----- bookmarks -----


async def test_bookmark_crud_round_trip(compat_env):
    t1, _ = _track_ids(compat_env)
    ok = _sub(_get(compat_env, "createBookmark", id=t1, position="60000",
                   comment="chapter 2"))
    assert ok["status"] == "ok"

    marks = _sub(_get(compat_env, "getBookmarks"))["bookmarks"]["bookmark"]
    assert len(marks) == 1
    assert marks[0]["position"] == 60000
    assert marks[0]["comment"] == "chapter 2"
    assert marks[0]["username"] == "alice"
    assert marks[0]["entry"]["id"] == t1

    _sub(_get(compat_env, "deleteBookmark", id=t1))
    body = _sub(_get(compat_env, "getBookmarks"))["bookmarks"]
    assert not body.get("bookmark")


async def test_create_bookmark_updates_position(compat_env):
    t1, _ = _track_ids(compat_env)
    _sub(_get(compat_env, "createBookmark", id=t1, position="1000"))
    _sub(_get(compat_env, "createBookmark", id=t1, position="9000"))
    marks = _sub(_get(compat_env, "getBookmarks"))["bookmarks"]["bookmark"]
    assert len(marks) == 1
    assert marks[0]["position"] == 9000


async def test_create_bookmark_requires_position(compat_env):
    t1, _ = _track_ids(compat_env)
    body = _sub(_get(compat_env, "createBookmark", id=t1))
    assert body["status"] == "failed"
    assert body["error"]["code"] == 10


async def test_create_bookmark_unknown_track_is_70(compat_env):
    body = _sub(_get(compat_env, "createBookmark", id="tr-nope", position="0"))
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70


async def test_bookmarks_xml_envelope(compat_env):
    t1, _ = _track_ids(compat_env)
    _sub(_get(compat_env, "createBookmark", id=t1, position="500"))
    q = {"v": "1.16.1", "c": "pytest", "apiKey": compat_env.secret}
    r = compat_env.client.get("/subsonic/rest/getBookmarks", params=q)
    text = r.content.decode()
    assert r.headers["content-type"].startswith("application/xml")
    assert "<bookmarks>" in text and "<bookmark" in text and "<entry" in text
