from unittest.mock import MagicMock

from api.v1.schemas.home import HomeSection, ServicePrompt
from api.v1.schemas.library import LibraryAlbum
from services.home.section_builders import HomeSectionBuilders


def _make_builders():
    transformers = MagicMock()
    transformers.library_album_to_home.side_effect = lambda a: {"album": a.album}
    transformers.library_artist_to_home.side_effect = lambda a: {"name": a.get("name")} if a.get("name") else None
    return HomeSectionBuilders(transformers)


class TestBuildRecentlyAdded:
    def test_returns_home_section(self):
        b = _make_builders()
        albums = [
            LibraryAlbum(artist="A", album=f"Album{i}")
            for i in range(20)
        ]
        section = b.build_recently_added_section(albums)
        assert isinstance(section, HomeSection)
        assert section.title == "Recently Added"
        assert section.type == "albums"
        assert len(section.items) == 15


class TestBuildLibraryArtists:
    def test_sorts_by_album_count(self):
        b = _make_builders()
        artists = [
            {"name": "Low", "mbid": "a", "album_count": 1},
            {"name": "High", "mbid": "b", "album_count": 10},
        ]
        section = b.build_library_artists_section(artists)
        assert isinstance(section, HomeSection)
        assert section.title == "Your Artists"
        assert len(section.items) <= 15


class TestBuildServicePrompts:
    def test_no_prompts_when_all_enabled(self):
        b = _make_builders()
        prompts = b.build_service_prompts(
            lb_enabled=True, download_client_configured=True, lfm_enabled=True
        )
        assert prompts == []

    def test_all_prompts_when_nothing_enabled(self):
        b = _make_builders()
        prompts = b.build_service_prompts(
            lb_enabled=False, download_client_configured=False, lfm_enabled=False
        )
        assert len(prompts) > 0
        services = {p.service for p in prompts}
        assert "download-client" in services

    def test_prompts_are_service_prompt_type(self):
        b = _make_builders()
        prompts = b.build_service_prompts(
            lb_enabled=False, download_client_configured=False, lfm_enabled=False
        )
        for p in prompts:
            assert isinstance(p, ServicePrompt)


class TestBuildGenreList:
    def test_returns_section_with_correct_shape(self):
        transformers = MagicMock()
        from api.v1.schemas.home import HomeGenre
        transformers.extract_genres_from_library.return_value = [
            HomeGenre(name="rock"), HomeGenre(name="pop")
        ]
        b = HomeSectionBuilders(transformers)
        albums = [
            LibraryAlbum(artist="A", album="X"),
        ]
        section = b.build_genre_list_section(albums)
        assert isinstance(section, HomeSection)
        assert section.type == "genres"
        assert len(section.items) == 2
