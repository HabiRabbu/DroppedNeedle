import pytest

from api.v1.schemas.settings import (
    is_official_musicbrainz,
    MusicBrainzConnectionSettings,
    _OFFICIAL_MB_RATE_LIMIT,
    _OFFICIAL_MB_CONCURRENT_SEARCHES,
)


class TestIsOfficialMusicBrainz:
    """Test the URL detection helper."""

    def test_official_https(self):
        assert is_official_musicbrainz("https://musicbrainz.org/ws/2") is True

    def test_official_http(self):
        assert is_official_musicbrainz("http://musicbrainz.org/ws/2") is True

    def test_official_www(self):
        assert is_official_musicbrainz("https://www.musicbrainz.org/ws/2") is True

    def test_official_uppercase(self):
        assert is_official_musicbrainz("https://MUSICBRAINZ.ORG/ws/2") is True

    def test_official_trailing_slash(self):
        assert is_official_musicbrainz("https://musicbrainz.org/ws/2/") is True

    def test_official_with_spaces(self):
        assert is_official_musicbrainz("  https://musicbrainz.org/ws/2  ") is True

    def test_custom_mirror(self):
        assert is_official_musicbrainz("https://my-mirror.example.com/ws/2") is False

    def test_localhost(self):
        assert is_official_musicbrainz("http://localhost:5000/ws/2") is False

    def test_empty_string(self):
        assert is_official_musicbrainz("") is False

    def test_not_a_url(self):
        assert is_official_musicbrainz("not a url") is False

    def test_subdomain_not_www(self):
        assert is_official_musicbrainz("https://api.musicbrainz.org/ws/2") is False


class TestMusicBrainzSettingsClamping:
    """Test that rate limits are clamped for official API."""

    def test_official_url_clamps_rate_limit(self):
        settings = MusicBrainzConnectionSettings(
            api_url="https://musicbrainz.org/ws/2",
            rate_limit=10.0,
            concurrent_searches=6,
        )
        assert settings.rate_limit == _OFFICIAL_MB_RATE_LIMIT

    def test_official_url_clamps_concurrent_searches(self):
        settings = MusicBrainzConnectionSettings(
            api_url="https://musicbrainz.org/ws/2",
            rate_limit=1.0,
            concurrent_searches=20,
        )
        assert settings.concurrent_searches == _OFFICIAL_MB_CONCURRENT_SEARCHES

    def test_official_url_clamps_both(self):
        settings = MusicBrainzConnectionSettings(
            api_url="https://musicbrainz.org/ws/2",
            rate_limit=50.0,
            concurrent_searches=30,
        )
        assert settings.rate_limit == _OFFICIAL_MB_RATE_LIMIT
        assert settings.concurrent_searches == _OFFICIAL_MB_CONCURRENT_SEARCHES

    def test_official_url_does_not_increase_low_values(self):
        settings = MusicBrainzConnectionSettings(
            api_url="https://musicbrainz.org/ws/2",
            rate_limit=0.5,
            concurrent_searches=3,
        )
        assert settings.rate_limit == 0.5
        assert settings.concurrent_searches == 3

    def test_custom_url_allows_high_rate_limit(self):
        settings = MusicBrainzConnectionSettings(
            api_url="https://my-mirror.example.com/ws/2",
            rate_limit=25.0,
            concurrent_searches=20,
        )
        assert settings.rate_limit == 25.0
        assert settings.concurrent_searches == 20

    def test_defaults_unchanged(self):
        settings = MusicBrainzConnectionSettings()
        assert settings.rate_limit == 1.0
        assert settings.concurrent_searches == 6
        assert settings.api_url == "https://musicbrainz.org/ws/2"


class TestInstanceId:
    """Test instance ID generation and retrieval."""

    def test_ensure_instance_id_generates_on_first_run(self, tmp_path):
        from core.config import Settings
        from services.preferences_service import PreferencesService

        config_path = tmp_path / "config.json"
        settings = Settings(config_file_path=config_path, root_app_dir=tmp_path)
        prefs = PreferencesService(settings)

        instance_id = prefs.get_instance_id()
        assert instance_id != "unknown"
        assert len(instance_id) == 36  # UUID format: 8-4-4-4-12

    def test_instance_id_is_stable_across_loads(self, tmp_path):
        from core.config import Settings
        from services.preferences_service import PreferencesService

        config_path = tmp_path / "config.json"
        settings = Settings(config_file_path=config_path, root_app_dir=tmp_path)
        prefs1 = PreferencesService(settings)
        id1 = prefs1.get_instance_id()

        # Create a new instance pointing to the same config
        prefs2 = PreferencesService(settings)
        id2 = prefs2.get_instance_id()

        assert id1 == id2

    def test_instance_id_in_user_agent(self, tmp_path):
        from core.config import Settings

        settings = Settings(
            instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            root_app_dir=tmp_path,
        )
        ua = settings.get_user_agent()
        assert "a1b2c3d4" in ua
        assert "DroppedNeedle/1.0" in ua

    def test_user_agent_unknown_when_no_instance_id(self, tmp_path):
        from core.config import Settings

        settings = Settings(instance_id="", root_app_dir=tmp_path)
        ua = settings.get_user_agent()
        assert "unknown" in ua
