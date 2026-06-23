import msgspec
import pytest
from api.v1.schemas.artist import ArtistInfo
from api.v1.schemas.album import AlbumInfo, AlbumBasicInfo
from api.v1.schemas.search import SearchResult
from api.v1.schemas.cache import CacheStats


AUDIODB_CDN = "https://www.theaudiodb.com/images/media"


def test_artist_info_audiodb_fields_default_to_none():
    artist = ArtistInfo(name="Test", musicbrainz_id="abc-123")
    for field in (
        "thumb_url",
        "fanart_url_2",
        "fanart_url_3",
        "fanart_url_4",
        "wide_thumb_url",
        "logo_url",
        "clearart_url",
        "cutout_url",
        "fanart_url",
        "banner_url",
    ):
        assert getattr(artist, field) is None, f"{field} should default to None"


def test_artist_info_audiodb_fields_serialized():
    fields = {
        "thumb_url": f"{AUDIODB_CDN}/thumb.jpg",
        "fanart_url_2": f"{AUDIODB_CDN}/fanart2.jpg",
        "fanart_url_3": f"{AUDIODB_CDN}/fanart3.jpg",
        "fanart_url_4": f"{AUDIODB_CDN}/fanart4.jpg",
        "wide_thumb_url": f"{AUDIODB_CDN}/wide.jpg",
        "logo_url": f"{AUDIODB_CDN}/logo.png",
        "clearart_url": f"{AUDIODB_CDN}/clearart.png",
        "cutout_url": f"{AUDIODB_CDN}/cutout.png",
    }
    artist = ArtistInfo(name="Test", musicbrainz_id="abc-123", **fields)
    data = msgspec.json.decode(msgspec.json.encode(artist))
    for key, value in fields.items():
        assert key in data, f"{key} missing from serialized output"
        assert data[key] == value


def test_artist_info_existing_fields_unchanged():
    artist = ArtistInfo(
        name="Artist",
        musicbrainz_id="mb-id",
        image="http://library/img.jpg",
        fanart_url="http://library/fanart.jpg",
    )
    assert artist.name == "Artist"
    assert artist.musicbrainz_id == "mb-id"
    assert artist.image == "http://library/img.jpg"
    assert artist.fanart_url == "http://library/fanart.jpg"
    assert artist.in_library is False
    assert artist.albums == []


def test_album_info_audiodb_fields_default_to_none():
    album = AlbumInfo(
        title="Test", musicbrainz_id="abc", artist_name="Artist", artist_id="xyz"
    )
    for field in (
        "album_thumb_url",
        "album_back_url",
        "album_cdart_url",
        "album_spine_url",
        "album_3d_case_url",
        "album_3d_flat_url",
        "album_3d_face_url",
        "album_3d_thumb_url",
        "cover_url",
    ):
        assert getattr(album, field) is None, f"{field} should default to None"


def test_album_info_audiodb_fields_serialized():
    fields = {
        "album_thumb_url": f"{AUDIODB_CDN}/album_thumb.jpg",
        "album_back_url": f"{AUDIODB_CDN}/album_back.jpg",
        "album_cdart_url": f"{AUDIODB_CDN}/cdart.png",
        "album_spine_url": f"{AUDIODB_CDN}/spine.jpg",
        "album_3d_case_url": f"{AUDIODB_CDN}/3dcase.png",
        "album_3d_flat_url": f"{AUDIODB_CDN}/3dflat.png",
        "album_3d_face_url": f"{AUDIODB_CDN}/3dface.png",
        "album_3d_thumb_url": f"{AUDIODB_CDN}/3dthumb.png",
    }
    album = AlbumInfo(
        title="Test", musicbrainz_id="abc", artist_name="Artist", artist_id="xyz",
        **fields,
    )
    data = msgspec.json.decode(msgspec.json.encode(album))
    for key, value in fields.items():
        assert key in data, f"{key} missing from serialized output"
        assert data[key] == value


def test_album_basic_info_includes_thumb():
    basic = AlbumBasicInfo(
        title="Test", musicbrainz_id="abc", artist_name="Artist", artist_id="xyz"
    )
    assert basic.album_thumb_url is None

    basic_with_thumb = AlbumBasicInfo(
        title="Test", musicbrainz_id="abc", artist_name="Artist", artist_id="xyz",
        album_thumb_url="https://cdn/thumb.jpg",
    )
    data = msgspec.json.decode(msgspec.json.encode(basic_with_thumb))
    assert "album_thumb_url" in data
    assert data["album_thumb_url"] == "https://cdn/thumb.jpg"


def test_search_result_audiodb_overlay_fields():
    result = SearchResult(type="artist", title="Test", musicbrainz_id="abc")
    assert result.thumb_url is None
    assert result.fanart_url is None
    assert result.banner_url is None
    assert result.album_thumb_url is None

    overlay = {
        "thumb_url": f"{AUDIODB_CDN}/thumb.jpg",
        "fanart_url": f"{AUDIODB_CDN}/fanart.jpg",
        "banner_url": f"{AUDIODB_CDN}/banner.jpg",
        "album_thumb_url": f"{AUDIODB_CDN}/album_thumb.jpg",
    }
    result_with = SearchResult(
        type="artist", title="Test", musicbrainz_id="abc", **overlay
    )
    data = msgspec.json.decode(msgspec.json.encode(result_with))
    for key, value in overlay.items():
        assert key in data, f"{key} missing from serialized output"
        assert data[key] == value


def test_cache_stats_audiodb_fields_default_to_zero():
    stats = CacheStats(
        memory_entries=0, memory_size_bytes=0, memory_size_mb=0.0,
        disk_metadata_count=0, disk_metadata_albums=0, disk_metadata_artists=0,
        disk_cover_count=0, disk_cover_size_bytes=0, disk_cover_size_mb=0.0,
        library_db_artist_count=0, library_db_album_count=0,
        library_db_size_bytes=0, library_db_size_mb=0.0,
        total_size_bytes=0, total_size_mb=0.0,
    )
    assert stats.disk_audiodb_artist_count == 0
    assert stats.disk_audiodb_album_count == 0


def test_cache_stats_audiodb_fields_serialized():
    stats = CacheStats(
        memory_entries=10, memory_size_bytes=2048, memory_size_mb=0.002,
        disk_metadata_count=50, disk_metadata_albums=30, disk_metadata_artists=20,
        disk_cover_count=15, disk_cover_size_bytes=1048576, disk_cover_size_mb=1.0,
        library_db_artist_count=5, library_db_album_count=8,
        library_db_size_bytes=4096, library_db_size_mb=0.004,
        total_size_bytes=1054720, total_size_mb=1.006,
        disk_audiodb_artist_count=42,
        disk_audiodb_album_count=99,
    )
    data = msgspec.json.decode(msgspec.json.encode(stats))
    assert data["disk_audiodb_artist_count"] == 42
    assert data["disk_audiodb_album_count"] == 99
    assert data["memory_entries"] == 10
    assert data["memory_size_bytes"] == 2048
    assert data["disk_metadata_count"] == 50
    assert data["disk_metadata_albums"] == 30
    assert data["disk_metadata_artists"] == 20
    assert data["disk_cover_count"] == 15
    assert data["disk_cover_size_bytes"] == 1048576
    assert data["library_db_artist_count"] == 5
    assert data["library_db_album_count"] == 8
    assert data["total_size_bytes"] == 1054720
