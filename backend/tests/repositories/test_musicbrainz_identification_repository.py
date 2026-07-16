from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.queue.priority_queue import RequestPriority
from models.identification import AlbumCandidate
from repositories.musicbrainz_identification_repository import (
    MusicBrainzIdentificationRepository,
)


@pytest.mark.asyncio
async def test_repository_normalizes_provider_payload_and_forwards_priority() -> None:
    musicbrainz = SimpleNamespace(
        search_albums=AsyncMock(return_value=[SimpleNamespace(musicbrainz_id="rg-1")]),
        search_recordings=AsyncMock(
            return_value=[
                SimpleNamespace(
                    release_groups=[SimpleNamespace(release_group_mbid="rg-1")]
                )
            ]
        ),
        get_release_group_by_id=AsyncMock(
            return_value={
                "id": "rg-1",
                "title": "Album",
                "primary-type": "Album",
                "secondary-types": [],
                "artist-credit": [{"name": "Artist", "artist": {"id": "artist-1"}}],
                "releases": [
                    {
                        "id": "release-1",
                        "status": "Official",
                        "date": "2026-01-01",
                        "media": [{"track-count": 1}],
                    }
                ],
            }
        ),
        get_release_by_id=AsyncMock(
            return_value={
                "date": "2026-01-01",
                "media": [
                    {
                        "position": 1,
                        "tracks": [
                            {
                                "position": 1,
                                "title": "Track",
                                "length": 180_000,
                                "recording": {"id": "recording-1"},
                            }
                        ],
                    }
                ],
            }
        ),
    )
    repository = MusicBrainzIdentificationRepository(musicbrainz)
    priority = RequestPriority.BACKGROUND_SYNC

    assert await repository.search_album_candidate_ids("query", 8, priority) == ["rg-1"]
    assert await repository.search_recording_candidate_ids(
        "Artist", "Track", 5, priority
    ) == ["rg-1"]
    candidate = await repository.get_album_candidate("rg-1", 1, priority)

    assert isinstance(candidate, AlbumCandidate)
    assert candidate.release_group_mbid == "rg-1"
    assert candidate.tracks[0].recording_mbid == "recording-1"
    assert candidate.tracks[0].duration_seconds == 180
    assert candidate.release_type == "album"
    assert all(
        call.kwargs["priority"] is priority
        for mock in (
            musicbrainz.search_albums,
            musicbrainz.search_recordings,
            musicbrainz.get_release_group_by_id,
            musicbrainz.get_release_by_id,
        )
        for call in mock.await_args_list
    )
