import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.v1.schemas.discover import DiscoverQueueEnrichment
from api.v1.schemas.settings import (
    ListenBrainzConnectionSettings,
    LastFmConnectionSettings,
    PrimaryMusicSourceSettings,
)
from services.discover_service import DiscoverService


def _make_prefs() -> MagicMock:
    prefs = MagicMock()
    prefs.get_listenbrainz_connection.return_value = ListenBrainzConnectionSettings(
        user_token="tok", username="u", enabled=True
    )
    prefs.get_lastfm_connection.return_value = LastFmConnectionSettings(
        api_key="k", shared_secret="s", session_key="sk", username="u", enabled=False
    )
    prefs.is_lastfm_enabled.return_value = False
    prefs.get_primary_music_source.return_value = PrimaryMusicSourceSettings(source="listenbrainz")
    jf = MagicMock()
    jf.enabled = False
    jf.jellyfin_url = ""
    jf.api_key = ""
    prefs.get_jellyfin_connection.return_value = jf
    download_client = MagicMock()
    download_client.enabled = False
    download_client.url = ""
    prefs.get_download_client_settings.return_value = download_client
    yt = MagicMock()
    yt.enabled = False
    yt.api_key = ""
    prefs.get_youtube_connection.return_value = yt
    lf = MagicMock()
    lf.enabled = False
    lf.music_path = ""
    prefs.get_local_files_connection.return_value = lf
    return prefs


def _make_service(
    memory_cache: MagicMock | None = None,
) -> tuple[DiscoverService, AsyncMock]:
    mb_repo = AsyncMock()
    service = DiscoverService(
        listenbrainz_repo=AsyncMock(),
        jellyfin_repo=AsyncMock(),
        library_repo=AsyncMock(),
        musicbrainz_repo=mb_repo,
        preferences_service=_make_prefs(),
        memory_cache=memory_cache,
    )
    return service, mb_repo


FAKE_ENRICHMENT = DiscoverQueueEnrichment(
    artist_mbid="artist-1",
    tags=["rock"],
    release_date="2020",
)

MBID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestEnrichSingleflight:
    @pytest.mark.asyncio
    async def test_concurrent_calls_run_enrichment_once(self):
        """Multiple concurrent enrich_queue_item calls for the same mbid should only invoke
        _do_enrich_queue_item once; all callers receive the same result."""
        service, mb_repo = _make_service(memory_cache=None)
        call_count = 0
        original_do_enrich = service._enrichment._do_enrich_queue_item

        async def counting_enrich(release_group_mbid: str, cache_key: str):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return FAKE_ENRICHMENT

        service._enrichment._do_enrich_queue_item = counting_enrich

        results = await asyncio.gather(
            service.enrich_queue_item(MBID),
            service.enrich_queue_item(MBID),
            service.enrich_queue_item(MBID),
        )

        assert call_count == 1
        assert all(r == FAKE_ENRICHMENT for r in results)

    @pytest.mark.asyncio
    async def test_singleflight_cleared_after_completion(self):
        """After enrichment completes, the in-flight dict should be empty so a second call
        runs the pipeline again (useful if the first result wasn't cached)."""
        service, _ = _make_service(memory_cache=None)

        async def quick_enrich(release_group_mbid: str, cache_key: str):
            return FAKE_ENRICHMENT

        service._enrichment._do_enrich_queue_item = quick_enrich

        await service.enrich_queue_item(MBID)
        assert MBID not in service._enrichment._enrich_in_flight

    @pytest.mark.asyncio
    async def test_singleflight_propagates_exception_to_all_waiters(self):
        """If enrichment raises, all concurrent callers should receive the same exception."""
        service, _ = _make_service(memory_cache=None)

        async def failing_enrich(release_group_mbid: str, cache_key: str):
            await asyncio.sleep(0.05)
            raise RuntimeError("MB rate limit")

        service._enrichment._do_enrich_queue_item = failing_enrich

        results = await asyncio.gather(
            service.enrich_queue_item(MBID),
            service.enrich_queue_item(MBID),
            service.enrich_queue_item(MBID),
            return_exceptions=True,
        )

        assert all(isinstance(r, RuntimeError) for r in results)
        assert all(str(r) == "MB rate limit" for r in results)
        assert MBID not in service._enrichment._enrich_in_flight

    @pytest.mark.asyncio
    async def test_memory_cache_hit_skips_singleflight(self):
        """If the enrichment is in the memory cache, singleflight should not be consulted."""
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=FAKE_ENRICHMENT)
        service, _ = _make_service(memory_cache=cache)

        call_count = 0

        async def should_not_run(release_group_mbid: str, cache_key: str):
            nonlocal call_count
            call_count += 1
            return FAKE_ENRICHMENT

        service._enrichment._do_enrich_queue_item = should_not_run

        result = await service.enrich_queue_item(MBID)
        assert result == FAKE_ENRICHMENT
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_memory_cache_miss_triggers_enrichment(self):
        """If the memory cache returns None, the enrichment pipeline should run."""
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
        service, _ = _make_service(memory_cache=cache)

        async def simple_enrich(release_group_mbid: str, cache_key: str):
            return FAKE_ENRICHMENT

        service._enrichment._do_enrich_queue_item = simple_enrich

        result = await service.enrich_queue_item(MBID)
        assert result == FAKE_ENRICHMENT

    @pytest.mark.asyncio
    async def test_different_mbids_run_independently(self):
        """Enrichment for different mbids should run independently (no dedup)."""
        service, _ = _make_service(memory_cache=None)
        call_mbids: list[str] = []

        async def tracking_enrich(release_group_mbid: str, cache_key: str):
            call_mbids.append(release_group_mbid)
            await asyncio.sleep(0.02)
            return FAKE_ENRICHMENT

        service._enrichment._do_enrich_queue_item = tracking_enrich

        mbid_a = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee"
        mbid_b = "bbbb2222-bbbb-cccc-dddd-eeeeeeeeeeee"
        await asyncio.gather(
            service.enrich_queue_item(mbid_a),
            service.enrich_queue_item(mbid_b),
        )

        assert len(call_mbids) == 2
        assert mbid_a in call_mbids
        assert mbid_b in call_mbids
