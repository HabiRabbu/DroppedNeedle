from io import BytesIO
from pathlib import Path
import shutil

import msgspec
from mutagen.apev2 import APEv2
from mutagen.id3 import ID3, TXXX
from mutagen.wave import WAVE
import pytest

from api.v1.schemas.library_management import (
    AUDIO_MANAGED_FIELD_NAMES,
    MANAGED_FIELD_NAMES,
    normalize_library_management_settings,
    picard_style_organizer_profile,
    build_initial_library_management_settings,
)
from infrastructure.audio.metadata_engine import (
    FORMAT_CAPABILITIES,
    AudioMetadataEngine,
)
from infrastructure.audio.riff_info import write_riff_info
from models.audio_metadata import (
    AudioWritePolicy,
    DesiredAudioDocument,
    DesiredAudioField,
    SemanticTagSnapshot,
)
from services.native.audio_write_planning_service import (
    AudioWritePlanningService,
    audio_write_policy_from_profile,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "library"
FORMATS = ("flac", "mp3", "ogg", "opus", "m4a", "aac", "wav", "wma")
ORDERED_FIELDS = {
    "artist",
    "album_artist",
    "artist_sort",
    "album_artist_sort",
    "release_type",
    "label",
    "catalog_number",
    "isrc",
    "musicbrainz_artist_id",
    "musicbrainz_album_artist_id",
    "musicbrainz_work_id",
    "composer",
    "lyricist",
    "conductor",
    "performer",
    "arranger",
    "remixer",
    "producer",
    "genre",
}
INTEGER_FIELDS = {
    "track_number",
    "total_tracks",
    "disc_number",
    "total_discs",
    "movement_number",
    "movement_count",
}


def _desired_value(field: str):
    if field in ORDERED_FIELDS:
        return ("Changed One", "Changed Two")
    if field in INTEGER_FIELDS:
        return 77
    if field == "compilation":
        return False
    if field in {"date", "original_date"}:
        return "2025-06-07"
    if field == "lyrics_synced":
        return "[00:01.000]Changed lyrics"
    if field.startswith("replaygain_"):
        return 0.5
    return f"Changed {field}"


def _one_field(name: str, action: str = "set", value=None) -> DesiredAudioDocument:
    return DesiredAudioDocument(
        fields=(
            DesiredAudioField(
                name=name,
                action=action,
                value=_desired_value(name)
                if value is None and action == "set"
                else value,
            ),
        )
    )


@pytest.mark.parametrize("audio_format", FORMATS)
def test_full_native_snapshot_is_json_serializable_and_restorable_contract(
    audio_format: str,
) -> None:
    path = FIXTURES / f"management_full.{audio_format}"
    snapshot = AudioMetadataEngine().snapshot(path)

    encoded = msgspec.json.encode(snapshot)
    decoded = msgspec.json.decode(encoded, type=SemanticTagSnapshot)

    assert decoded == snapshot
    assert snapshot.snapshot_version == 1
    assert snapshot.adapter_version == "1"
    assert snapshot.artwork[0].content
    assert snapshot.file_attributes.permission_bits > 0
    assert snapshot.technical.file_size_bytes == path.stat().st_size
    if audio_format in {"mp3", "wav"}:
        assert snapshot.native_tags.encoded_id3.startswith(b"ID3")
        restored_id3 = ID3(BytesIO(snapshot.native_tags.encoded_id3))
        assert "TXXX:CUSTOM_KEEP" in restored_id3
        assert restored_id3.getall("APIC")
    else:
        assert snapshot.native_tags.entries
        assert any(
            "custom_keep" in entry.key.casefold()
            for entry in snapshot.native_tags.entries
        )


@pytest.mark.parametrize("audio_format", FORMATS)
def test_every_managed_field_has_an_explicit_format_plan(audio_format: str) -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / f"management_full.{audio_format}")
    capabilities = FORMAT_CAPABILITIES[audio_format]

    for field in AUDIO_MANAGED_FIELD_NAMES:
        plan = engine.plan(current, _one_field(field), AudioWritePolicy())
        unsupported_message = f"{field} is not supported by the {audio_format} adapter"
        if field in capabilities.unsupported_fields:
            assert unsupported_message in plan.blockers
        else:
            assert unsupported_message not in plan.blockers
            assert plan.blockers == ()
        assert plan.mutations[0].name == field
        assert plan.snapshot.native_tags == current.native_tags


def test_unchanged_set_clear_merge_and_profile_preserve_are_distinct() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full.flac")
    desired = DesiredAudioDocument(
        fields=(
            DesiredAudioField(name="track_number", action="unchanged"),
            DesiredAudioField(name="album", action="set", value="Changed Album"),
            DesiredAudioField(name="barcode", action="clear"),
            DesiredAudioField(name="genre", action="merge", value=("ambient", "Jazz")),
            DesiredAudioField(name="title", action="set", value="Changed Title"),
        )
    )

    plan = engine.plan(current, desired, AudioWritePolicy(preserve_fields=("title",)))
    by_name = {mutation.name: mutation for mutation in plan.mutations}

    assert by_name["track_number"].operation == "unchanged"
    assert by_name["album"].operation == "set"
    assert by_name["album"].after == "Changed Album"
    assert by_name["barcode"].operation == "clear"
    assert by_name["barcode"].after is None
    assert by_name["genre"].operation == "merge"
    assert by_name["genre"].after == ("ambient", "Jazz", "Electronic")
    assert by_name["title"].operation == "preserve"
    assert by_name["title"].after == "Management Track"
    assert plan.requires_write is True


def test_ordinary_writes_preserve_all_raw_tags_and_scrub_is_explicit() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full.flac")
    empty = DesiredAudioDocument(fields=())

    ordinary = engine.plan(current, empty, AudioWritePolicy())
    scrub = engine.plan(
        current,
        empty,
        AudioWritePolicy(
            scrub_unmanaged_tags=True,
            preserve_fields=("custom_keep",),
        ),
    )
    scrub_art = engine.plan(
        current,
        empty,
        AudioWritePolicy(
            scrub_unmanaged_tags=True,
            preserve_embedded_art_during_scrub=False,
        ),
    )

    assert ordinary.scrubbed_raw_keys == ()
    assert set(ordinary.preserved_raw_keys) == {value.key for value in current.raw_tags}
    assert ordinary.requires_write is False
    assert any(key.casefold() == "custom_keep" for key in scrub.preserved_raw_keys)
    assert any(key.casefold() == "title" for key in scrub.scrubbed_raw_keys)
    assert scrub.preserve_embedded_artwork is True
    assert scrub.desired_artwork == current.artwork
    assert scrub_art.preserve_embedded_artwork is False
    assert scrub_art.desired_artwork == ()


def test_id3v23_loss_is_blocked_by_default_or_explicitly_warned() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full.mp3")
    desired = _one_field("artist", value=("One", "Two"))

    strict = engine.plan(
        current,
        desired,
        AudioWritePolicy(id3_version="2.3", id3_text_encoding="utf16"),
    )
    advanced = engine.plan(
        current,
        desired,
        AudioWritePolicy(
            id3_version="2.3",
            id3_text_encoding="utf16",
            strict_capability_gate=False,
        ),
    )
    unsupported = engine.plan(
        current,
        _one_field("disc_subtitle"),
        AudioWritePolicy(id3_version="2.3", id3_text_encoding="utf16"),
    )

    assert any("joined" in blocker for blocker in strict.blockers)
    assert not any("joined" in blocker for blocker in advanced.blockers)
    assert any("joined" in warning for warning in advanced.warnings)
    assert any(
        "no Picard ID3v2.3 representation" in value for value in unsupported.blockers
    )


def test_independently_written_id3v23_fixture_is_probed_and_snapshotted() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full_v23.mp3")

    snapshot = engine.snapshot(FIXTURES / "management_full_v23.mp3")
    decoded = msgspec.json.decode(
        msgspec.json.encode(snapshot), type=SemanticTagSnapshot
    )

    assert current.probe.tag_version == "2.3.0"
    assert current.metadata.value_for("title") == "Management Track"
    assert decoded.probe.tag_version == "2.3.0"
    assert decoded.native_tags.encoded_id3.startswith(b"ID3")


def test_constrained_genre_primary_only_is_an_explicit_warned_projection() -> None:
    current = AudioMetadataEngine().read(FIXTURES / "management_full.wav")
    plan = AudioMetadataEngine().plan(
        current,
        _one_field("genre", value=("Rock", "Pop")),
        AudioWritePolicy(
            wav_tag_policy="riff_info",
            constrained_genres_primary_only=True,
        ),
    )

    assert plan.mutations[0].after == ("Rock",)
    assert plan.blockers == ()
    assert any("primary value" in warning for warning in plan.warnings)


def test_wav_riff_and_raw_aac_policies_block_unrepresentable_writes() -> None:
    engine = AudioMetadataEngine()
    wav = engine.read(FIXTURES / "management_full.wav")
    aac = engine.read(FIXTURES / "management_full.aac")

    riff = engine.plan(
        wav,
        _one_field("label"),
        AudioWritePolicy(wav_tag_policy="riff_info"),
    )
    no_write = engine.plan(
        aac,
        _one_field("title"),
        AudioWritePolicy(raw_aac_tag_policy="do_not_write"),
    )
    remove = engine.plan(
        aac,
        _one_field("title"),
        AudioWritePolicy(raw_aac_tag_policy="remove_apev2"),
    )

    assert any("RIFF INFO" in value for value in riff.blockers)
    assert any("configured not to write" in value for value in no_write.blockers)
    assert "remove_apev2_from_aac" in remove.cleanup_actions
    assert any("cannot also publish" in value for value in remove.blockers)


def test_cleanup_controls_are_planned_only_when_auxiliary_tags_exist(
    tmp_path: Path,
) -> None:
    engine = AudioMetadataEngine()
    mp3 = tmp_path / "with-ape.mp3"
    flac = tmp_path / "with-id3.flac"
    shutil.copyfile(FIXTURES / "management_full.mp3", mp3)
    shutil.copyfile(FIXTURES / "management_full.flac", flac)
    ape = APEv2()
    ape["CUSTOM_APE"] = "preserve me"
    ape.save(mp3)
    id3 = ID3()
    id3.add(TXXX(encoding=3, desc="CUSTOM_ID3", text=["remove me"]))
    id3.save(flac)

    mp3_plan = engine.plan(
        engine.read(mp3),
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(mp3_apev2_policy="remove"),
    )
    flac_plan = engine.plan(
        engine.read(flac),
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(remove_id3_from_flac=True),
    )

    assert mp3_plan.cleanup_actions == ("remove_apev2_from_mp3",)
    assert mp3_plan.snapshot.native_tags.auxiliary_entries
    assert flac_plan.cleanup_actions == ("remove_id3_from_flac",)
    assert flac_plan.snapshot.native_tags.auxiliary_encoded_id3.startswith(b"ID3")


def test_wav_preserve_existing_requires_a_detectable_existing_tag_scheme(
    tmp_path: Path,
) -> None:
    path = tmp_path / "untagged.wav"
    shutil.copyfile(FIXTURES / "management_full.wav", path)
    audio = WAVE(path)
    audio.delete()
    write_riff_info(path, {})
    current = AudioMetadataEngine().read(path)

    plan = AudioMetadataEngine().plan(
        current,
        _one_field("title"),
        AudioWritePolicy(wav_tag_policy="preserve_existing"),
    )

    assert current.probe.tag_version is None
    assert any("could not be verified" in value for value in plan.blockers)


def test_profile_conversion_and_custom_preserve_fields() -> None:
    profile = picard_style_organizer_profile()
    profile.metadata.preserve_fields = ["CUSTOM_KEEP"]
    profile.metadata.format_compatibility.id3_version = "2.3"
    profile.metadata.format_compatibility.id3_text_encoding = "utf16"
    profile.file_behavior.strict_capability_gate = False
    policy = audio_write_policy_from_profile(profile)

    assert policy.preserve_fields == ("CUSTOM_KEEP",)
    assert policy.id3_version == "2.3"
    assert policy.id3_text_encoding == "utf16"
    assert policy.strict_capability_gate is False

    settings = build_initial_library_management_settings()
    settings.profiles[0].metadata.preserve_fields = ["CUSTOM_KEEP"]
    normalized = normalize_library_management_settings(settings)
    assert normalized.profiles[0].metadata.preserve_fields == ["CUSTOM_KEEP"]


def test_invalid_preserve_names_and_id3v23_utf8_are_rejected() -> None:
    settings = build_initial_library_management_settings()
    settings.profiles[0].metadata.preserve_fields = ["BAD\x00FIELD"]
    with pytest.raises(ValueError, match="preserved field name"):
        normalize_library_management_settings(settings)

    settings = build_initial_library_management_settings()
    settings.profiles[0].metadata.format_compatibility.id3_version = "2.3"
    settings.profiles[0].metadata.format_compatibility.id3_text_encoding = "utf8"
    with pytest.raises(ValueError, match="requires UTF-16"):
        normalize_library_management_settings(settings)


def test_planning_service_applies_profile_policy_without_writing() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full.flac")
    profile = picard_style_organizer_profile()
    profile.metadata.preserve_fields = ["title"]

    plan = AudioWritePlanningService(engine).plan(
        current=current,
        desired=_one_field("title"),
        profile=profile,
    )

    assert plan.mutations[0].operation == "preserve"
    assert plan.requires_write is False
    assert current.metadata.value_for("title") == "Management Track"
