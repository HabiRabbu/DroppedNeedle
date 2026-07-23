import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import msgspec
import pytest

from api.v1.schemas.library_management import (
    PICARD_ORGANIZER_PROFILE_ID,
    LibraryManagementRootAssignment,
    profile_revision,
)
from core.exceptions import AutomaticManagementHoldError, ExternalServiceError
from infrastructure.audio.metadata_engine import (
    AudioMetadataEngine,
    legacy_audio_projection,
)
from models.audio import AudioTag
from models.library_management import (
    METADATA_UNAVAILABLE,
    INSUFFICIENT_SPACE,
    PROFILE_CHANGED,
    TRACK_NOT_MAPPED,
    LibraryManagementImportBundle,
    LibraryManagementImportFile,
)
from models.library_management_enrichment import (
    ReplayGainAnalysis,
    ReplayGainTrackResult,
)
from services.native.automatic_import_management_service import (
    AutomaticImportManagementService,
)
from services.native.library_management_profile_service import (
    LibraryManagementProfileService,
)
from tests.services.native.test_library_management_planner import _configured, _planner


def _service(  # noqa: ANN001, ANN202
    tmp_path: Path, preferences, store, *, lyrics=None, replaygain=None
):
    planner = _planner(tmp_path, store, preferences)
    profiles = LibraryManagementProfileService(preferences)
    return (
        AutomaticImportManagementService(
            profiles,
            planner,
            planner._canonical,
            planner._effective,
            planner._genres,
            planner._artwork,
            planner._audio,
            planner._write_planner,
            planner._naming,
            planner._tagging,
            lyrics=lyrics,
            replaygain=replaygain,
        ),
        planner,
    )


def _activate(preferences, policy_revision: str, *, stale: bool = False) -> None:  # noqa: ANN001
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    settings.root_assignments = [
        LibraryManagementRootAssignment(
            root_id="root-1",
            profile_id=profile.id,
            enabled=True,
            automatic_acquisitions=True,
            automatic_drop_imports=False,
            activation_profile_revision=(
                "stale-profile" if stale else profile_revision(profile)
            ),
            activation_policy_revision=policy_revision,
            activation_settings_revision=current.settings_revision,
            activation_preview_token="confirmed",
            activation_preview_hash="confirmed-hash",
            activation_confirmed_at=100.0,
        )
    ]
    preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )


def _bundle(
    tmp_path: Path,
    catalog_source: Path,
    policy_revision: str,
    *,
    origin: str = "acquisition",
    authoritative: bool = True,
) -> LibraryManagementImportBundle:
    source = tmp_path / f"incoming-{origin}.flac"
    shutil.copy2(catalog_source, source)
    _tag, info = legacy_audio_projection(AudioMetadataEngine().read(source))
    return LibraryManagementImportBundle(
        idempotency_key=f"{origin}:automatic-preparation",
        origin=origin,
        policy_revision=policy_revision,
        files=(
            LibraryManagementImportFile(
                ordinal=0,
                input_path=str(source),
                destination_root_id="root-1",
                destination_relative_path="Incoming/01 Original.flac",
                tag=AudioTag(
                    title="Aria",
                    artist="Glenn Gould",
                    album="Goldberg Variations",
                    album_artist="Johann Sebastian Bach; Glenn Gould",
                    disc_number=1,
                    track_number=1,
                ),
                info=info,
                release_group_mbid="dcff25f1-702d-3b5e-b0da-d48172e6e62a",
                release_mbid="aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b",
                recording_mbid="33333333-3333-4333-8333-333333333333",
                release_track_mbid="22222222-2222-4222-8222-222222222222",
                medium_position=1,
                release_track_position=1,
                authoritative_mapping=authoritative,
                confidence=1.0,
                source="download",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_acquisition_toggle_pins_full_projection_but_drop_toggle_is_independent(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    _activate(preferences, policy_revision)
    service, _planner_value = _service(tmp_path, preferences, store)

    acquisition = await service.prepare(_bundle(tmp_path, source, policy_revision))
    acquisition_repeat = await service.prepare(
        _bundle(tmp_path, source, policy_revision)
    )
    drop = await service.prepare(
        _bundle(tmp_path, source, policy_revision, origin="drop_import")
    )

    managed = acquisition.files[0]
    assert managed.pinned_profile is not None
    assert managed.desired_document is not None
    assert managed.metadata_snapshot_id is not None
    assert managed.release_track_mbid == "22222222-2222-4222-8222-222222222222"
    assert managed.baseline_relative_path == "Incoming/01 Original.flac"
    assert managed.destination_relative_path != managed.baseline_relative_path
    assert acquisition_repeat.idempotency_key == acquisition.idempotency_key
    assert msgspec.to_builtins(drop) == msgspec.to_builtins(
        _bundle(tmp_path, source, policy_revision, origin="drop_import")
    )


@pytest.mark.asyncio
async def test_automatic_import_holds_stale_activation_and_unmapped_files(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    _activate(preferences, policy_revision, stale=True)
    service, _planner_value = _service(tmp_path, preferences, store)

    with pytest.raises(AutomaticManagementHoldError) as stale:
        await service.prepare(_bundle(tmp_path, source, policy_revision))
    assert stale.value.reason_code == PROFILE_CHANGED

    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    settings.root_assignments[0].activation_profile_revision = profile_revision(profile)
    preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    with pytest.raises(AutomaticManagementHoldError) as unmapped:
        await service.prepare(
            _bundle(tmp_path, source, policy_revision, authoritative=False)
        )
    assert unmapped.value.reason_code == TRACK_NOT_MAPPED


@pytest.mark.asyncio
async def test_required_musicbrainz_failure_holds_whole_automatic_unit(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    _activate(preferences, policy_revision)
    service, planner = _service(tmp_path, preferences, store)
    planner._canonical._musicbrainz.get_canonical_release.side_effect = (
        ExternalServiceError("provider unavailable")
    )

    with pytest.raises(AutomaticManagementHoldError) as held:
        await service.prepare(_bundle(tmp_path, source, policy_revision))

    assert held.value.reason_code == METADATA_UNAVAILABLE


@pytest.mark.asyncio
async def test_optional_genre_outage_preserves_local_value_and_records_warning(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.genres.sources = ["listenbrainz"]
    preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    _activate(preferences, policy_revision)
    service, _planner_value = _service(tmp_path, preferences, store)

    prepared = await service.prepare(_bundle(tmp_path, source, policy_revision))

    request = prepared.files[0]
    genre = next(
        field for field in request.desired_document.fields if field.name == "genre"
    )
    assert request.management_warnings == ("genre:listenbrainz",)
    assert genre.action == "unchanged"


@pytest.mark.asyncio
async def test_automatic_import_pins_replaygain_before_publication(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "replace"
    preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    _activate(preferences, policy_revision)
    bundle = _bundle(tmp_path, source, policy_revision)
    replaygain = AsyncMock()
    replaygain.analyze.return_value = ReplayGainAnalysis(
        status="available",
        analyzer_version="loudgain 0.6.8",
        tracks=(
            ReplayGainTrackResult(
                source_path=bundle.files[0].input_path,
                track_gain_db=1.25,
                track_peak=0.5,
                album_gain_db=2.5,
                album_peak=0.6,
            ),
        ),
    )
    service, _planner_value = _service(
        tmp_path, preferences, store, replaygain=replaygain
    )

    prepared = await service.prepare(bundle)
    desired = {
        value.name: value.value for value in prepared.files[0].desired_document.fields
    }

    assert desired["replaygain_track_gain"] == 1.25
    assert desired["replaygain_track_peak"] == 0.5
    assert desired["replaygain_album_gain"] == 2.5
    assert desired["replaygain_album_peak"] == 0.6
    replaygain.analyze.assert_awaited_once_with(
        (Path(bundle.files[0].input_path),), album_aware=True
    )


@pytest.mark.asyncio
async def test_required_replaygain_failure_holds_automatic_unit(
    tmp_path: Path,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "replace"
    profile.enrichment.replaygain.required = True
    preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    _activate(preferences, policy_revision)
    replaygain = AsyncMock()
    replaygain.analyze.return_value = ReplayGainAnalysis(
        status="deferred", reason="Analyzer unavailable."
    )
    service, _planner_value = _service(
        tmp_path, preferences, store, replaygain=replaygain
    )

    with pytest.raises(AutomaticManagementHoldError) as held:
        await service.prepare(_bundle(tmp_path, source, policy_revision))

    assert held.value.reason_code == METADATA_UNAVAILABLE


@pytest.mark.asyncio
async def test_automatic_import_holds_before_staging_when_capacity_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, source, preferences, store, _settings, policy_revision = _configured(
        tmp_path
    )
    _activate(preferences, policy_revision)
    service, _planner_value = _service(tmp_path, preferences, store)
    monkeypatch.setattr(
        "services.native.automatic_import_management_service.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )

    with pytest.raises(AutomaticManagementHoldError) as held:
        await service.prepare(_bundle(tmp_path, source, policy_revision))

    assert held.value.reason_code == INSUFFICIENT_SPACE
