"""Translate profile settings into the infrastructure write-planning contract."""

from __future__ import annotations

from api.v1.schemas.library_management import LibraryManagementProfile
from infrastructure.audio.metadata_engine import AudioMetadataEngine
from models.audio_metadata import (
    AudioWritePlan,
    AudioWritePolicy,
    DesiredAudioDocument,
    ReadAudioDocument,
)
from models.library_management_scripts import CustomTagValue


def audio_write_policy_from_profile(
    profile: LibraryManagementProfile,
) -> AudioWritePolicy:
    metadata = profile.metadata
    compatibility = metadata.format_compatibility
    return AudioWritePolicy(
        preserve_fields=tuple(metadata.preserve_fields),
        scrub_unmanaged_tags=metadata.scrub_unmanaged_tags,
        preserve_embedded_art_during_scrub=(
            metadata.preserve_embedded_art_during_scrub
        ),
        preserve_timestamps=profile.file_behavior.preserve_timestamps,
        preserve_permissions=profile.file_behavior.preserve_permissions,
        strict_capability_gate=profile.file_behavior.strict_capability_gate,
        id3_version=compatibility.id3_version,
        id3v23_join_delimiter=compatibility.id3v23_join_delimiter,
        id3_text_encoding=compatibility.id3_text_encoding,
        remove_id3_from_flac=compatibility.remove_id3_from_flac,
        mp3_apev2_policy=compatibility.mp3_apev2_policy,
        raw_aac_tag_policy=compatibility.raw_aac_tag_policy,
        wav_tag_policy=compatibility.wav_tag_policy,
        constrained_genres_primary_only=(
            compatibility.constrained_genres_primary_only
            or profile.genres.write_primary_only_for_constrained_formats
        ),
    )


class AudioWritePlanningService:
    def __init__(self, engine: AudioMetadataEngine) -> None:
        self._engine = engine

    def plan(
        self,
        *,
        current: ReadAudioDocument,
        desired: DesiredAudioDocument,
        profile: LibraryManagementProfile,
    ) -> AudioWritePlan:
        return self._engine.plan(
            current, desired, audio_write_policy_from_profile(profile)
        )

    def custom_tags(
        self,
        *,
        current: ReadAudioDocument,
        profile: LibraryManagementProfile,
    ) -> tuple[CustomTagValue, ...]:
        return self._engine.custom_tags(
            current, audio_write_policy_from_profile(profile)
        )
