import json

import msgspec
import pytest

from api.v1.schemas.advanced_settings import AdvancedSettings, AdvancedSettingsFrontend
from api.v1.schemas.discover import (
    DiscoverResponse,
    PlaylistProfile,
    PlaylistSuggestionsRequest,
    PlaylistSuggestionsResponse,
    RadioRequest,
)
from api.v1.schemas.home import HomeSection


class TestDiscoverResponseNewFields:
    def test_default_daily_mixes_is_empty_list(self) -> None:
        resp = DiscoverResponse()
        assert resp.daily_mixes == []

    def test_default_radio_sections_is_empty_list(self) -> None:
        resp = DiscoverResponse()
        assert resp.radio_sections == []

    def test_default_top_picks_is_none(self) -> None:
        resp = DiscoverResponse()
        assert resp.top_picks is None
        assert resp.listeners_like_you is None
        assert resp.anniversaries is None
        assert resp.new_from_followed is None

    def test_default_unexplored_genres_is_none(self) -> None:
        resp = DiscoverResponse()
        assert resp.unexplored_genres is None

    def test_roundtrip_with_new_fields(self) -> None:
        from api.v1.schemas.discover import TopPickItem, TopPicksSection
        from api.v1.schemas.home import HomeAlbum

        section = HomeSection(title="Test", type="albums")
        picks = TopPicksSection(
            items=[
                TopPickItem(
                    album=HomeAlbum(name="Album", mbid="rg-1"),
                    match_pct=78,
                    reasons=["Because you listen to X"],
                )
            ],
            source="listenbrainz",
        )
        resp = DiscoverResponse(
            daily_mixes=[section],
            radio_sections=[section],
            top_picks=picks,
            unexplored_genres=section,
        )
        data = json.loads(msgspec.json.encode(resp))
        assert len(data["daily_mixes"]) == 1
        assert data["top_picks"]["items"][0]["match_pct"] == 78
        assert data["unexplored_genres"]["title"] == "Test"
        assert len(data["radio_sections"]) == 1

    def test_roundtrip_preserves_existing_fields(self) -> None:
        resp = DiscoverResponse(refreshing=True, discover_queue_enabled=False)
        data = json.loads(msgspec.json.encode(resp))
        assert data["refreshing"] is True
        assert data["discover_queue_enabled"] is False
        assert data["daily_mixes"] == []
        assert data["top_picks"] is None


class TestRadioRequest:
    def test_required_fields(self) -> None:
        req = RadioRequest(seed_type="artist", seed_id="abc-123")
        assert req.seed_type == "artist"
        assert req.seed_id == "abc-123"
        assert req.count == 10
        assert req.source is None

    def test_roundtrip(self) -> None:
        req = RadioRequest(seed_type="genre", seed_id="rock", count=20, source="listenbrainz")
        data = msgspec.json.encode(req)
        decoded = msgspec.json.decode(data, type=RadioRequest)
        assert decoded.seed_type == "genre"
        assert decoded.count == 20

    def test_invalid_seed_type_rejected(self) -> None:
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(b'{"seed_type":"invalid","seed_id":"x"}', type=RadioRequest)


class TestPlaylistProfile:
    def test_defaults(self) -> None:
        profile = PlaylistProfile()
        assert profile.artist_mbids == []
        assert profile.genre_distribution == {}
        assert profile.track_count == 0

    def test_roundtrip(self) -> None:
        profile = PlaylistProfile(
            artist_mbids=["a", "b"],
            genre_distribution={"rock": ["a"], "jazz": ["b"]},
            track_count=42,
        )
        data = msgspec.json.encode(profile)
        decoded = msgspec.json.decode(data, type=PlaylistProfile)
        assert decoded.artist_mbids == ["a", "b"]
        assert decoded.genre_distribution["rock"] == ["a"]


class TestPlaylistSuggestionsRequest:
    def test_required_fields(self) -> None:
        req = PlaylistSuggestionsRequest(playlist_id="pl-1")
        assert req.playlist_id == "pl-1"
        assert req.count == 10
        assert req.source is None

    def test_roundtrip(self) -> None:
        req = PlaylistSuggestionsRequest(playlist_id="pl-1", count=5)
        data = msgspec.json.encode(req)
        decoded = msgspec.json.decode(data, type=PlaylistSuggestionsRequest)
        assert decoded.count == 5

    def test_source_lastfm_roundtrip(self) -> None:
        req = PlaylistSuggestionsRequest(playlist_id="pl-1", source="lastfm")
        data = msgspec.json.encode(req)
        decoded = msgspec.json.decode(data, type=PlaylistSuggestionsRequest)
        assert decoded.source == "lastfm"

    def test_source_listenbrainz_roundtrip(self) -> None:
        req = PlaylistSuggestionsRequest(playlist_id="pl-1", source="listenbrainz")
        data = msgspec.json.encode(req)
        decoded = msgspec.json.decode(data, type=PlaylistSuggestionsRequest)
        assert decoded.source == "listenbrainz"

    def test_invalid_source_rejected(self) -> None:
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(
                b'{"playlist_id":"x","source":"invalid"}',
                type=PlaylistSuggestionsRequest,
            )


class TestPlaylistSuggestionsResponse:
    def test_roundtrip(self) -> None:
        section = HomeSection(title="Sug", type="albums")
        profile = PlaylistProfile(track_count=10)
        resp = PlaylistSuggestionsResponse(suggestions=section, playlist_id="pl-1", profile=profile)
        data = json.loads(msgspec.json.encode(resp))
        assert data["playlist_id"] == "pl-1"
        assert data["profile"]["track_count"] == 10
        assert data["suggestions"]["title"] == "Sug"


class TestAdvancedSettingsDiscoverPicks:
    def test_defaults_on_internal(self) -> None:
        settings = AdvancedSettings()
        assert settings.discover_picks_genre_affinity_weight == 0.7
        assert settings.discover_picks_count == 12

    def test_defaults_on_user_facing(self) -> None:
        uf = AdvancedSettingsFrontend()
        assert uf.discover_picks_genre_affinity_weight == 0.7
        assert uf.discover_picks_count == 12

    def test_roundtrip_internal_to_user_to_internal(self) -> None:
        original = AdvancedSettings(
            discover_picks_genre_affinity_weight=0.5,
            discover_picks_count=20,
        )
        uf = AdvancedSettingsFrontend.from_backend(original)
        assert uf.discover_picks_genre_affinity_weight == 0.5
        assert uf.discover_picks_count == 20
        back = uf.to_backend()
        assert back.discover_picks_genre_affinity_weight == 0.5
        assert back.discover_picks_count == 20

    def test_validation_rejects_out_of_range_affinity(self) -> None:
        with pytest.raises(msgspec.ValidationError):
            AdvancedSettings(discover_picks_genre_affinity_weight=1.5)

    def test_validation_rejects_out_of_range_count(self) -> None:
        with pytest.raises(msgspec.ValidationError):
            AdvancedSettings(discover_picks_count=0)
