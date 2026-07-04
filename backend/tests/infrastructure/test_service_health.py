from infrastructure.service_health import ServiceHealthRegistry


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_mark_and_is_degraded():
    clock = _Clock()
    reg = ServiceHealthRegistry(clock=clock)
    reg.mark_degraded("listenbrainz", "popularity", message="down", fallback="lastfm", ttl_seconds=300)

    assert reg.is_degraded("listenbrainz", "popularity")
    assert reg.is_degraded("listenbrainz")  # any capability
    assert not reg.is_degraded("musicbrainz")


def test_heal_clears_a_capability_instantly():
    clock = _Clock()
    reg = ServiceHealthRegistry(clock=clock)
    reg.mark_degraded("listenbrainz", "popularity", message="down", fallback="lastfm", ttl_seconds=1800)
    reg.mark_degraded("listenbrainz", "listens", message="down", ttl_seconds=1800)

    reg.heal("listenbrainz", "popularity")  # upstream recovered

    assert not reg.is_degraded("listenbrainz", "popularity")  # healed before its TTL
    assert reg.is_degraded("listenbrainz", "listens")  # other capability untouched
    reg.heal("listenbrainz", "does-not-exist")  # no-op, must not raise


def test_current_reports_entry_details():
    clock = _Clock()
    reg = ServiceHealthRegistry(clock=clock)
    reg.mark_degraded("listenbrainz", "popularity", message="LB down", fallback="lastfm")
    clock.t += 42  # 42s later

    entries = reg.current()
    assert len(entries) == 1
    e = entries[0]
    assert e.service == "listenbrainz"
    assert e.capability == "popularity"
    assert e.fallback == "lastfm"
    assert e.message == "LB down"
    assert e.degraded_seconds == 42


def test_ttl_slides_forward_on_refresh():
    clock = _Clock()
    reg = ServiceHealthRegistry(clock=clock)
    reg.mark_degraded("listenbrainz", "popularity", message="down", ttl_seconds=300)
    since = reg.current()[0].degraded_seconds  # 0

    clock.t += 250
    reg.mark_degraded("listenbrainz", "popularity", message="down", ttl_seconds=300)  # refresh
    clock.t += 250  # 500s after first mark, but only 250s after refresh
    assert reg.is_degraded("listenbrainz", "popularity")  # still live
    # 'since' preserved across refresh -> degraded_seconds grows from the first mark
    assert reg.current()[0].degraded_seconds == 500
    assert since == 0


def test_auto_expires_after_ttl():
    clock = _Clock()
    reg = ServiceHealthRegistry(clock=clock)
    reg.mark_degraded("listenbrainz", "popularity", message="down", ttl_seconds=300)

    clock.t += 301
    assert not reg.is_degraded("listenbrainz", "popularity")
    assert reg.current() == []  # pruned
