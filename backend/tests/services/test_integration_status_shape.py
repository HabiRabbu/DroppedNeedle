import msgspec

from api.v1.schemas.common import IntegrationStatus


def test_integration_status_has_download_client_and_library_not_lidarr():
    status = IntegrationStatus(
        listenbrainz=False,
        jellyfin=False,
        download_client=False,
        youtube=False,
        lastfm=False,
    )
    data = msgspec.to_builtins(status)
    assert "download_client" in data
    assert "library" in data
    assert "lidarr" not in data


def test_integration_status_fields():
    fields = IntegrationStatus.__struct_fields__
    assert "download_client" in fields
    assert "library" in fields
    assert "lidarr" not in fields
