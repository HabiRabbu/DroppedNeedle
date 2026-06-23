from api.v1.schemas.artist import FollowStatusResponse
from models.artist import ArtistInfo


def test_artist_info_uses_in_library_not_in_lidarr():
    fields = ArtistInfo.__struct_fields__
    assert "in_library" in fields
    assert "in_lidarr" not in fields


def test_follow_status_response_uses_follow_semantics():
    fields = FollowStatusResponse.__struct_fields__
    assert "followed" in fields
    assert "auto_download_state" in fields
    assert "monitored" not in fields
