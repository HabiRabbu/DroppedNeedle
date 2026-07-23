import msgspec
import pytest

from api.v1.schemas.library_management import (
    LEGACY_NAMING_PROFILE_ID,
    LEGACY_NAMING_SCRIPT_ID,
    MANAGED_FIELD_NAMES,
    PICARD_ORGANIZER_PROFILE_ID,
    LibraryManagementSettings,
    ManagedFieldSettings,
    build_initial_library_management_settings,
    normalize_library_management_settings,
    profile_revision,
    settings_revision,
)


def _round_trip(
    settings: LibraryManagementSettings,
) -> LibraryManagementSettings:
    return msgspec.convert(
        msgspec.to_builtins(settings), type=LibraryManagementSettings
    )


def test_picard_preset_is_available_but_no_root_is_activated() -> None:
    settings = build_initial_library_management_settings("{artist}/{title}.{ext}")

    assert settings.default_profile_id == PICARD_ORGANIZER_PROFILE_ID
    assert settings.root_assignments == []
    assert {profile.id for profile in settings.profiles} == {
        PICARD_ORGANIZER_PROFILE_ID,
        LEGACY_NAMING_PROFILE_ID,
    }
    organizer = next(
        profile
        for profile in settings.profiles
        if profile.id == PICARD_ORGANIZER_PROFILE_ID
    )
    assert {field.field for field in organizer.metadata.fields} == set(
        MANAGED_FIELD_NAMES
    )
    assert organizer.metadata.scrub_unmanaged_tags is False
    assert organizer.artwork.embedded_enabled is True
    assert organizer.artwork.external_enabled is True
    assert organizer.artwork.download_size == "full"
    assert "cover.jpg" in organizer.artwork.local_file_patterns
    assert organizer.organization.rename_enabled is True
    assert organizer.organization.move_enabled is True
    assert organizer.organization.move_sidecars is True
    assert organizer.enrichment.lyrics.enabled is False
    assert organizer.enrichment.lyrics.write_plain is True
    assert organizer.enrichment.lyrics.write_synced is False
    assert organizer.enrichment.replaygain.enabled is False


def test_legacy_template_is_copied_into_an_unassigned_path_only_profile() -> None:
    source = "{albumartist}/{album}/{track:02d} {title}.{ext}"
    settings = build_initial_library_management_settings(source)
    script = next(
        value
        for value in settings.naming_scripts
        if value.id == LEGACY_NAMING_SCRIPT_ID
    )
    profile = next(
        value for value in settings.profiles if value.id == LEGACY_NAMING_PROFILE_ID
    )

    assert script.source == source
    assert profile.organization.naming_script_id == script.id
    assert profile.metadata.enabled is False
    assert profile.genres.enabled is False
    assert profile.artwork.embedded_enabled is False
    assert profile.artwork.external_enabled is False
    assert settings.root_assignments == []


def test_nested_settings_round_trip_and_revisions_are_stable() -> None:
    settings = build_initial_library_management_settings()
    first_revision = settings_revision(settings)
    first_profiles = {profile.id: profile.revision for profile in settings.profiles}

    decoded = normalize_library_management_settings(_round_trip(settings))

    assert settings_revision(decoded) == first_revision
    assert {
        profile.id: profile.revision for profile in decoded.profiles
    } == first_profiles


def test_profile_revision_changes_when_a_capability_changes() -> None:
    settings = build_initial_library_management_settings()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    previous = profile.revision

    profile.organization.move_enabled = False
    profile.revision = profile_revision(profile)

    assert profile.revision != previous


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda settings: settings.profiles[0].metadata.fields.append(
                ManagedFieldSettings(field="invented_field")
            ),
            "Unknown managed field",
        ),
        (
            lambda settings: settings.profiles[0].organization.sidecar_patterns.append(
                "../cover.jpg"
            ),
            "must stay inside",
        ),
        (
            lambda settings: settings.profiles[0].artwork.local_file_patterns.append(
                "**/*"
            ),
            "must stay inside",
        ),
        (
            lambda settings: setattr(
                settings.profiles[0].file_behavior, "reject_symlinks", False
            ),
            "cannot follow symlinks",
        ),
    ],
)
def test_unsafe_or_unknown_profile_values_are_rejected(mutation, message: str) -> None:
    settings = build_initial_library_management_settings()
    mutation(settings)

    with pytest.raises(ValueError, match=message):
        normalize_library_management_settings(settings)


def test_duplicate_profile_ids_are_rejected() -> None:
    settings = build_initial_library_management_settings()
    settings.profiles[1].id = settings.profiles[0].id

    with pytest.raises(ValueError, match="unique ID"):
        normalize_library_management_settings(settings)
