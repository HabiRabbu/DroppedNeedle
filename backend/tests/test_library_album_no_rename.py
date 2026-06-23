import msgspec

from models.library import LibraryAlbum


def test_library_album_serializes_musicbrainz_id_not_foreign_album_id():
    album = LibraryAlbum(
        artist="Artist",
        album="Album",
        musicbrainz_id="11111111-1111-1111-1111-111111111111",
    )
    encoded = msgspec.json.encode(album).decode()
    assert "musicbrainz_id" in encoded
    assert "foreignAlbumId" not in encoded
