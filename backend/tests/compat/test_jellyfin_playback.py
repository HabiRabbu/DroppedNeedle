"""T5.2 - Jellyfin Sessions/Playing reporting + scrobble rule."""

import json
import sqlite3

import pytest

pytestmark = pytest.mark.asyncio

_TICKS = 10_000_000


def _h(env):
    return {"Authorization": f'MediaBrowser Token="{env.secret}", Client="jellyfin-test"'}


def _jget(env, path, **params):
    r = env.client.get(f"/jellyfin{path}", params=params, headers=_h(env))
    assert r.status_code == 200, r.content
    return json.loads(r.content)


def _a_track(env):
    album_id = _jget(env, "/Items", IncludeItemTypes="MusicAlbum")["Items"][0]["Id"]
    track = _jget(env, "/Items", ParentId=album_id)["Items"][0]
    return track["Id"], track["RunTimeTicks"]


def _plays(env):
    conn = sqlite3.connect(env.phs.db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM play_history").fetchall()
    finally:
        conn.close()


async def test_stopped_past_threshold_records_play(compat_env):
    tid, runtime = _a_track(compat_env)
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Stopped", headers=_h(compat_env),
        json={"ItemId": tid, "PositionTicks": runtime, "RunTimeTicks": runtime},
    )
    assert r.status_code == 204
    rows = _plays(compat_env)
    assert len(rows) == 1
    assert rows[0]["source"] == "jellyfin-test"


async def test_stopped_below_threshold_records_nothing(compat_env):
    tid, runtime = _a_track(compat_env)
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Stopped", headers=_h(compat_env),
        json={"ItemId": tid, "PositionTicks": int(runtime * 0.05), "RunTimeTicks": runtime},
    )
    assert r.status_code == 204
    assert _plays(compat_env) == []


async def test_stopped_failed_records_nothing(compat_env):
    tid, runtime = _a_track(compat_env)
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Stopped", headers=_h(compat_env),
        json={"ItemId": tid, "PositionTicks": runtime, "Failed": True},
    )
    assert r.status_code == 204
    assert _plays(compat_env) == []


async def test_start_then_stopped_records_one_play(compat_env):
    tid, runtime = _a_track(compat_env)
    s = compat_env.client.post(
        "/jellyfin/Sessions/Playing", headers=_h(compat_env),
        json={"ItemId": tid, "PlaySessionId": "ps-1"},
    )
    assert s.status_code == 204
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Stopped", headers=_h(compat_env),
        json={"ItemId": tid, "PlaySessionId": "ps-1", "PositionTicks": runtime,
              "RunTimeTicks": runtime},
    )
    assert r.status_code == 204
    assert len(_plays(compat_env)) == 1  # now-playing did not double-count


async def test_progress_with_eventname_does_not_400(compat_env):
    tid, _ = _a_track(compat_env)
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Progress", headers=_h(compat_env),
        json={"ItemId": tid, "PositionTicks": 5_000_000, "EventName": "timeupdate"},
    )
    assert r.status_code == 204
    assert _plays(compat_env) == []  # progress is not a play


async def test_ping_204(compat_env):
    r = compat_env.client.post("/jellyfin/Sessions/Playing/Ping", headers=_h(compat_env))
    assert r.status_code == 204


async def test_capabilities_full_204(compat_env):
    r = compat_env.client.post(
        "/jellyfin/Sessions/Capabilities/Full", headers=_h(compat_env),
        json={"PlayableMediaTypes": ["Audio"], "SupportsMediaControl": True},
    )
    assert r.status_code == 204


async def test_position_omitted_counts_as_played(compat_env):
    tid, _ = _a_track(compat_env)
    r = compat_env.client.post(
        "/jellyfin/Sessions/Playing/Stopped", headers=_h(compat_env),
        json={"ItemId": tid},  # no PositionTicks -> counts (reference s6)
    )
    assert r.status_code == 204
    assert len(_plays(compat_env)) == 1
