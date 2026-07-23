import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import msgspec
import pytest

from api.v1.schemas.library_management import picard_style_organizer_profile
from core.exceptions import ProviderIdentityRequiredError, ResourceNotFoundError
from infrastructure.queue.priority_queue import RequestPriority
from models.library_management_canonical import (
    AcceptedAlbumManagementIdentity,
    AcceptedTrackManagementIdentity,
)
from repositories.musicbrainz_management_models import MbManagementRelease
from services.native.canonical_release_metadata_service import (
    CanonicalReleaseMetadataService,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "musicbrainz"
    / "management_release.json"
)


def _release() -> MbManagementRelease:
    return msgspec.json.decode(_FIXTURE.read_bytes(), type=MbManagementRelease)


def _identity(
    *,
    release_mbid: str | None = "aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b",
    release_track_mbid: str | None = "22222222-2222-4222-8222-222222222222",
    recording_mbid: str | None = "33333333-3333-4333-8333-333333333333",
) -> AcceptedAlbumManagementIdentity:
    return AcceptedAlbumManagementIdentity(
        local_album_id="album-1",
        album_revision=4,
        identity_revision=3,
        release_group_mbid="dcff25f1-702d-3b5e-b0da-d48172e6e62a",
        release_mbid=release_mbid,
        tracks=(
            AcceptedTrackManagementIdentity(
                local_track_id="track-1",
                track_revision=7,
                identity_revision=2,
                recording_mbid=recording_mbid,
                release_mbid=release_mbid,
                release_track_mbid=release_track_mbid,
                medium_position=1,
                release_track_position=1,
            ),
        ),
    )


def _service(identity, release=None, *, clock=lambda: 100.0):
    store = AsyncMock()
    store.get_accepted_library_management_identity.return_value = identity
    store.put_management_metadata_snapshot.side_effect = lambda snapshot: snapshot
    musicbrainz = AsyncMock()
    musicbrainz.get_canonical_release.return_value = release or _release()
    return (
        CanonicalReleaseMetadataService(store, musicbrainz, clock=clock),
        store,
        musicbrainz,
    )


@pytest.mark.asyncio
async def test_requires_existing_album_and_specific_accepted_edition() -> None:
    missing_service, _, _ = _service(None)
    with pytest.raises(ResourceNotFoundError, match="album not found"):
        await missing_service.build(
            local_album_id="missing", profile=picard_style_organizer_profile()
        )

    edition_service, _, musicbrainz = _service(_identity(release_mbid=None))
    with pytest.raises(ProviderIdentityRequiredError, match="specific MusicBrainz"):
        await edition_service.build(
            local_album_id="album-1", profile=picard_style_organizer_profile()
        )
    musicbrainz.get_canonical_release.assert_not_awaited()


@pytest.mark.asyncio
async def test_requires_release_track_and_recording_mapping_for_every_file() -> None:
    service, _, _ = _service(_identity(release_track_mbid=None))
    with pytest.raises(ProviderIdentityRequiredError, match="Every selected file"):
        await service.build(
            local_album_id="album-1", profile=picard_style_organizer_profile()
        )


@pytest.mark.asyncio
async def test_projects_credited_picard_metadata_and_identity_alignment() -> None:
    service, store, musicbrainz = _service(_identity())
    projection = await service.build(
        local_album_id="album-1",
        local_track_ids=("track-1",),
        profile=picard_style_organizer_profile(),
        priority=RequestPriority.BACKGROUND_SYNC,
    )
    document = projection.document
    track = document.media[0].tracks[0]

    assert document.artist_credits[0].display_name == "Johann Sebastian Bach"
    assert document.artist_credits[0].sort_name == "Bach, Johann Sebastian"
    assert document.date is not None and document.date.value == "1982-10"
    assert document.date.precision == "month"
    assert document.original_date is not None
    assert document.original_date.value == "1956"
    assert document.original_date.precision == "year"
    assert document.total_discs == 1
    assert track.total_tracks == 1
    assert track.disc_subtitle == "Aria and Variations"
    assert track.track_number_text == "A1"
    assert track.identifiers.release_track_mbid == (
        "22222222-2222-4222-8222-222222222222"
    )
    assert track.identifiers.recording_mbid == ("33333333-3333-4333-8333-333333333333")
    assert track.identifiers.isrcs == ("USSM18200001",)
    assert track.work_title == "Goldberg Variations, BWV 988: Aria"
    assert {credit.role for credit in track.relationship_credits} == {
        "composer",
        "performer",
    }
    assert musicbrainz.get_canonical_release.await_args.kwargs["priority"] is (
        RequestPriority.BACKGROUND_SYNC
    )
    includes = musicbrainz.get_canonical_release.await_args.kwargs["includes"]
    assert "recordings" in includes
    assert "work-rels" in includes
    snapshot = store.put_management_metadata_snapshot.await_args.args[0]
    payload = json.loads(snapshot.canonical_payload_json)
    assert payload["media"][0]["tracks"][0]["local_track_id"] == "track-1"
    assert snapshot.payload_sha256 == projection.payload_sha256


@pytest.mark.asyncio
async def test_canonical_standardization_and_locale_translation_are_independent() -> (
    None
):
    release = _release()
    release.artist_credit[0].name = "J. S. Bach (credited)"

    canonical_profile = picard_style_organizer_profile()
    canonical_profile.metadata.artist_credits.standardization = "canonical"
    canonical_service, _, _ = _service(_identity(), release)
    canonical = await canonical_service.build(
        local_album_id="album-1", profile=canonical_profile
    )
    assert canonical.document.artist_credits[0].display_name == "Johann Sebastian Bach"
    assert canonical.document.artist_credits[0].credited_name == "J. S. Bach (credited)"

    translated_profile = copy.deepcopy(canonical_profile)
    translated_profile.metadata.artist_credits.translate_names = True
    translated_profile.metadata.artist_credits.preferred_locales = ["en-GB"]
    translated_service, _, musicbrainz = _service(_identity(), release)
    translated = await translated_service.build(
        local_album_id="album-1", profile=translated_profile
    )
    assert translated.document.artist_credits[0].display_name == "J. S. Bach"
    assert musicbrainz.get_canonical_release.await_args.kwargs["preferred_locales"] == (
        "en-GB",
    )
    assert "aliases" in musicbrainz.get_canonical_release.await_args.kwargs["includes"]


@pytest.mark.asyncio
async def test_relationship_controls_can_disable_projection_and_includes() -> None:
    profile = picard_style_organizer_profile()
    profile.metadata.relationships.enabled = False
    service, _, musicbrainz = _service(_identity())

    projection = await service.build(local_album_id="album-1", profile=profile)

    assert projection.document.media[0].tracks[0].relationship_credits == ()
    includes = musicbrainz.get_canonical_release.await_args.kwargs["includes"]
    assert "work-rels" not in includes
    assert "recording-level-rels" not in includes


@pytest.mark.asyncio
async def test_compilation_uses_musicbrainz_various_artists_identity() -> None:
    release = _release()
    release.artist_credit = [release.artist_credit[0]]
    release.artist_credit[0].artist.id = "89ad4ac3-39f7-470e-963a-56509c546377"
    release.artist_credit[0].artist.name = "Various Artists"
    release.artist_credit[0].name = "Various Artists"
    service, _, _ = _service(_identity(), release)

    projection = await service.build(
        local_album_id="album-1", profile=picard_style_organizer_profile()
    )
    assert projection.document.compilation is True


@pytest.mark.asyncio
async def test_missing_provider_entity_and_changed_mapping_return_to_review() -> None:
    missing_service, _, musicbrainz = _service(_identity())
    musicbrainz.get_canonical_release.return_value = None
    with pytest.raises(ProviderIdentityRequiredError, match="no longer exists"):
        await missing_service.build(
            local_album_id="album-1", profile=picard_style_organizer_profile()
        )

    changed_service, _, _ = _service(_identity(recording_mbid="different-recording"))
    with pytest.raises(ProviderIdentityRequiredError, match="no longer matches"):
        await changed_service.build(
            local_album_id="album-1", profile=picard_style_organizer_profile()
        )


@pytest.mark.asyncio
async def test_snapshot_identity_and_payload_are_deterministic() -> None:
    clock_values = iter((100.0, 200.0))
    service, store, _ = _service(_identity(), clock=lambda: next(clock_values))
    profile = picard_style_organizer_profile()

    first = await service.build(local_album_id="album-1", profile=profile)
    second = await service.build(local_album_id="album-1", profile=profile)

    assert first.metadata_snapshot_id == second.metadata_snapshot_id
    assert first.input_hash == second.input_hash
    assert first.payload_sha256 == second.payload_sha256
    first_snapshot = store.put_management_metadata_snapshot.await_args_list[0].args[0]
    second_snapshot = store.put_management_metadata_snapshot.await_args_list[1].args[0]
    assert (
        first_snapshot.canonical_payload_json == second_snapshot.canonical_payload_json
    )
    assert first_snapshot.fetched_at != second_snapshot.fetched_at
