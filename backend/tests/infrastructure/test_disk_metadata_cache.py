import hashlib
import json

import pytest

from api.v1.schemas.album import AlbumInfo
from infrastructure.cache.disk_cache import DiskMetadataCache
from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages


def _cache_hash(identifier: str) -> str:
    return hashlib.sha1(f"{DiskMetadataCache._CACHE_VERSION}:{identifier}".encode()).hexdigest()


@pytest.mark.asyncio
async def test_set_album_serializes_msgspec_struct_as_mapping(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    mbid = "4549a80c-efe6-4386-b3a2-4b4a918eb31f"
    album_info = AlbumInfo(
        title="The Moon Song",
        musicbrainz_id=mbid,
        artist_name="beabadoobee",
        artist_id="88d17133-abbc-42db-9526-4e2c1db60336",
        in_library=True,
        selected_release_mbid="2a835d2e-907e-4b9c-8b36-e8ad4c2e8257",
    )

    await cache.set_album(mbid, album_info, is_monitored=True)

    cache_hash = _cache_hash(mbid)
    cache_file = tmp_path / "persistent" / "albums" / f"{cache_hash}.json"
    payload = json.loads(cache_file.read_text())

    assert isinstance(payload, dict)
    assert payload["musicbrainz_id"] == mbid
    assert payload["selected_release_mbid"] == "2a835d2e-907e-4b9c-8b36-e8ad4c2e8257"

    cached = await cache.get_album(mbid)
    assert isinstance(cached, dict)
    assert cached["title"] == "The Moon Song"
    assert cached["selected_release_mbid"] == "2a835d2e-907e-4b9c-8b36-e8ad4c2e8257"


@pytest.mark.asyncio
async def test_get_album_deletes_corrupt_string_payload(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    mbid = "8e1e9e51-38dc-4df3-8027-a0ada37d4674"

    cache_hash = _cache_hash(mbid)
    cache_file = tmp_path / "persistent" / "albums" / f"{cache_hash}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps("AlbumInfo(title='Corrupt')"))

    cached = await cache.get_album(mbid)

    assert cached is None
    assert not cache_file.exists()


@pytest.mark.asyncio
async def test_audiodb_artist_entity_routing(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    mbid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    images = AudioDBArtistImages(
        thumb_url="https://example.com/thumb.jpg",
        fanart_url="https://example.com/fanart.jpg",
        lookup_source="mbid",
        matched_mbid=mbid,
    )

    await cache._set_entity("audiodb_artist", mbid, images, is_monitored=False, ttl_seconds=None)

    result = await cache._get_entity("audiodb_artist", mbid)
    assert result is not None
    assert result["thumb_url"] == "https://example.com/thumb.jpg"
    assert result["fanart_url"] == "https://example.com/fanart.jpg"
    assert result["lookup_source"] == "mbid"

    cache_hash = _cache_hash(mbid)
    data_file = tmp_path / "recent" / "audiodb_artists" / f"{cache_hash}.json"
    assert data_file.exists()


@pytest.mark.asyncio
async def test_audiodb_album_entity_routing(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    mbid = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    images = AudioDBAlbumImages(
        album_thumb_url="https://example.com/album_thumb.jpg",
        album_back_url="https://example.com/album_back.jpg",
        lookup_source="name",
        matched_mbid=mbid,
    )

    await cache._set_entity("audiodb_album", mbid, images, is_monitored=True, ttl_seconds=None)

    result = await cache._get_entity("audiodb_album", mbid)
    assert result is not None
    assert result["album_thumb_url"] == "https://example.com/album_thumb.jpg"
    assert result["album_back_url"] == "https://example.com/album_back.jpg"
    assert result["lookup_source"] == "name"

    cache_hash = _cache_hash(mbid)
    persistent_file = tmp_path / "persistent" / "audiodb_albums" / f"{cache_hash}.json"
    assert persistent_file.exists()


@pytest.mark.asyncio
async def test_get_stats_counts_audiodb_entries(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)

    artist_images = AudioDBArtistImages(thumb_url="https://example.com/a.jpg")
    album_images = AudioDBAlbumImages(album_thumb_url="https://example.com/b.jpg")

    await cache._set_entity("audiodb_artist", "artist-1", artist_images, is_monitored=False, ttl_seconds=None)
    await cache._set_entity("audiodb_artist", "artist-2", artist_images, is_monitored=True, ttl_seconds=None)
    await cache._set_entity("audiodb_album", "album-1", album_images, is_monitored=False, ttl_seconds=None)

    stats = cache.get_stats()
    assert stats["audiodb_artist_count"] == 2
    assert stats["audiodb_album_count"] == 1
    assert stats["album_count"] == 0
    assert stats["artist_count"] == 0
    assert stats["total_count"] == 3


@pytest.mark.asyncio
async def test_clear_audiodb_isolates_from_other_entities(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    album_mbid = "c3d4e5f6-a7b8-9012-cdef-123456789012"
    album_info = AlbumInfo(
        title="Regular Album",
        musicbrainz_id=album_mbid,
        artist_name="Test Artist",
        artist_id="d4e5f6a7-b8c9-0123-defa-234567890123",
        in_library=False,
    )
    await cache.set_album(album_mbid, album_info, is_monitored=False)

    artist_images = AudioDBArtistImages(thumb_url="https://example.com/thumb.jpg")
    album_images = AudioDBAlbumImages(album_thumb_url="https://example.com/album.jpg")
    await cache._set_entity("audiodb_artist", "adb-artist-1", artist_images, is_monitored=False, ttl_seconds=None)
    await cache._set_entity("audiodb_album", "adb-album-1", album_images, is_monitored=True, ttl_seconds=None)

    stats_before = cache.get_stats()
    assert stats_before["audiodb_artist_count"] == 1
    assert stats_before["audiodb_album_count"] == 1
    assert stats_before["album_count"] == 1

    await cache.clear_audiodb()

    stats_after = cache.get_stats()
    assert stats_after["audiodb_artist_count"] == 0
    assert stats_after["audiodb_album_count"] == 0
    assert stats_after["album_count"] == 1

    regular_album = await cache.get_album(album_mbid)
    assert regular_album is not None
    assert regular_album["title"] == "Regular Album"


@pytest.mark.asyncio
async def test_audiodb_monitored_persistent_vs_recent(tmp_path):
    cache = DiskMetadataCache(base_path=tmp_path)
    mbid = "e5f6a7b8-c9d0-1234-efab-567890123456"
    images = AudioDBArtistImages(thumb_url="https://example.com/t.jpg")

    await cache._set_entity("audiodb_artist", mbid, images, is_monitored=True, ttl_seconds=None)

    cache_hash = _cache_hash(mbid)
    persistent_file = tmp_path / "persistent" / "audiodb_artists" / f"{cache_hash}.json"
    recent_file = tmp_path / "recent" / "audiodb_artists" / f"{cache_hash}.json"
    assert persistent_file.exists()
    assert not recent_file.exists()

    await cache._set_entity("audiodb_artist", mbid, images, is_monitored=False, ttl_seconds=None)

    assert not persistent_file.exists()
    assert recent_file.exists()
