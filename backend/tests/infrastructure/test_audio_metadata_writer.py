from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil

from PIL import Image
from mutagen.apev2 import APEv2, error as APEError
from mutagen.id3 import ID3, TXXX
from mutagen.wave import WAVE
import pytest

from api.v1.schemas.library_management import MANAGED_FIELD_NAMES
from core.exceptions import AudioWriteError
from infrastructure.audio import metadata_writer
from infrastructure.audio.metadata_engine import (
    FORMAT_CAPABILITIES,
    AudioMetadataEngine,
)
from infrastructure.audio.riff_info import read_riff_info, write_riff_info
from models.audio_metadata import (
    AudioWritePolicy,
    DesiredAudioDocument,
    DesiredCustomTag,
    DesiredAudioField,
    EmbeddedArtworkDescriptor,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stage(tmp_path: Path, fixture_name: str) -> tuple[Path, Path, str]:
    source = FIXTURES / fixture_name
    staged = tmp_path / fixture_name
    shutil.copy2(source, staged)
    return source, staged, _sha256(source)


def _desired_value(name: str):
    if name == "lyrics_plain":
        return "Writer lyric one\nWriter lyric two"
    if name == "lyrics_synced":
        return "[00:01.000]Writer lyric one\n[00:03.250]Writer lyric two"
    if name.endswith("_gain"):
        return 3.75
    if name.endswith("_peak"):
        return 0.192705
    if name == "artist":
        return ("Writer Artist One", "Writer Artist Two")
    if name == "album_artist":
        return ("Writer Album Artist",)
    if name == "performer":
        return ("Writer Player (guitar)", "Writer Singer")
    if name in ORDERED_FIELDS:
        return (f"Writer {name} One", f"Writer {name} Two")
    if name in INTEGER_FIELDS:
        return 7
    if name == "compilation":
        return False
    if name in {"date", "original_date"}:
        return "2025-06-07"
    return f"Writer {name} – 日本語"


def _full_desired(audio_format: str) -> DesiredAudioDocument:
    supported = FORMAT_CAPABILITIES[audio_format].supported_fields
    fields = tuple(
        DesiredAudioField(name=name, action="set", value=_desired_value(name))
        for name in supported
    )
    return DesiredAudioDocument(
        fields=fields,
        artist_display="Writer Artist One feat. Writer Artist Two",
        album_artist_display="Writer Album Artist",
    )


def _artwork(
    image_type: str,
    image_format: str,
    size: tuple[int, int],
) -> EmbeddedArtworkDescriptor:
    output = BytesIO()
    Image.new("RGB", size, (32, 96, 160)).save(output, format=image_format)
    content = output.getvalue()
    mime_type = "image/jpeg" if image_format == "JPEG" else "image/png"
    return EmbeddedArtworkDescriptor(
        image_type=image_type,
        mime_type=mime_type,
        description=f"Writer {image_type}",
        width=size[0],
        height=size[1],
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        format_supported=True,
    )


@pytest.mark.parametrize("audio_format", FORMATS)
def test_all_supported_fields_write_only_to_staged_copy(
    audio_format: str,
    tmp_path: Path,
) -> None:
    source, staged, source_hash = _stage(tmp_path, f"management_full.{audio_format}")
    os.chmod(staged, 0o640)
    expected_atime = 1_700_000_100_000_000_000
    expected_mtime = 1_700_000_000_000_000_000
    os.utime(staged, ns=(expected_atime, expected_mtime))
    engine = AudioMetadataEngine()
    before = engine.read(staged)
    plan = engine.plan(before, _full_desired(audio_format), AudioWritePolicy())

    result = engine.apply(staged, plan)

    assert plan.blockers == ()
    assert _sha256(source) == source_hash
    assert result.file_size_bytes == staged.stat().st_size
    for mutation in plan.mutations:
        assert result.document.metadata.value_for(mutation.name) == mutation.after
    assert result.document.technical.sample_rate_hz == before.technical.sample_rate_hz
    assert result.document.technical.channels == before.technical.channels
    assert any("custom_keep" in raw.key.casefold() for raw in result.document.raw_tags)
    stat_result = staged.stat()
    assert stat_result.st_mode & 0o777 == 0o640
    assert stat_result.st_atime_ns == expected_atime
    assert stat_result.st_mtime_ns == expected_mtime
    assert result.file_sha256 == _sha256(staged)


@pytest.mark.parametrize("audio_format", FORMATS)
def test_snapshot_mutate_restore_recovers_native_semantics(
    audio_format: str,
    tmp_path: Path,
) -> None:
    source, staged, source_hash = _stage(tmp_path, f"management_full.{audio_format}")
    engine = AudioMetadataEngine()
    snapshot = engine.snapshot(staged)
    desired = DesiredAudioDocument(
        fields=(
            DesiredAudioField(name="title", action="set", value="Temporary title"),
            DesiredAudioField(name="genre", action="set", value=("Temporary",)),
        )
    )

    plan = engine.plan(engine.read(staged), desired, AudioWritePolicy())
    engine.apply(staged, plan)
    restored = engine.restore(staged, snapshot)

    assert _sha256(source) == source_hash
    assert restored.document.metadata == snapshot.metadata
    assert restored.document.artwork == snapshot.artwork
    assert restored.document.native_tags == snapshot.native_tags
    assert restored.document.technical == snapshot.technical
    assert staged.stat().st_mode & 0o777 == snapshot.file_attributes.permission_bits
    assert staged.stat().st_mtime_ns == snapshot.file_attributes.mtime_ns


def test_id3v23_write_materializes_encoding_and_join_policy(tmp_path: Path) -> None:
    _source, staged, _source_hash = _stage(tmp_path, "management_full_v23.mp3")
    engine = AudioMetadataEngine()
    desired = DesiredAudioDocument(
        fields=(
            DesiredAudioField(
                name="artist",
                action="set",
                value=("First Artist", "Second Artist"),
            ),
        ),
        artist_display="First Artist; Second Artist",
    )
    policy = AudioWritePolicy(
        id3_version="2.3",
        id3_text_encoding="utf16",
        id3v23_join_delimiter="; ",
        strict_capability_gate=False,
    )

    plan = engine.plan(engine.read(staged), desired, policy)
    result = engine.apply(staged, plan)
    tags = ID3(staged)

    assert result.document.probe.tag_version == "2.3.0"
    assert result.document.metadata.strings_for("artist") == (
        "First Artist; Second Artist",
    )
    assert tags.version == (2, 3, 0)
    assert tags["TPE1"].encoding == 1
    assert any("joined" in warning for warning in result.warnings)


@pytest.mark.parametrize("audio_format", FORMATS)
def test_scrub_preserves_named_semantic_and_custom_tags(
    audio_format: str,
    tmp_path: Path,
) -> None:
    _source, staged, _source_hash = _stage(tmp_path, f"management_full.{audio_format}")
    engine = AudioMetadataEngine()
    before = engine.read(staged)
    plan = engine.plan(
        before,
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(
            scrub_unmanaged_tags=True,
            preserve_fields=("title", "CUSTOM_KEEP"),
        ),
    )

    result = engine.apply(staged, plan)

    assert result.document.metadata.value_for("title") == before.metadata.value_for(
        "title"
    )
    assert result.document.metadata.value_for("album") is None
    assert any("custom_keep" in raw.key.casefold() for raw in result.document.raw_tags)
    assert result.document.artwork == before.artwork


def test_pure_riff_info_write_and_restore_never_adds_id3(tmp_path: Path) -> None:
    _source, staged, _source_hash = _stage(tmp_path, "management_full_riff.wav")
    engine = AudioMetadataEngine()
    snapshot = engine.snapshot(staged)
    desired = DesiredAudioDocument(
        fields=(
            DesiredAudioField(name="title", action="set", value="New RIFF title"),
            DesiredAudioField(name="genre", action="set", value=("Jazz",)),
        )
    )

    plan = engine.plan(
        engine.read(staged),
        desired,
        AudioWritePolicy(wav_tag_policy="preserve_existing"),
    )
    result = engine.apply(staged, plan)

    assert plan.compatibility.wav_tag_policy == "riff_info"
    assert result.document.probe.tag_format == "RIFF INFO"
    assert result.document.probe.tag_version is None
    assert result.document.native_tags.encoded_id3 is None
    assert result.document.metadata.value_for("title") == "New RIFF title"
    assert any("XTRA" in raw.key for raw in result.document.raw_tags)

    restored = engine.restore(staged, snapshot)
    assert restored.document.native_tags == snapshot.native_tags
    assert restored.document.probe.tag_format == "RIFF INFO"
    assert restored.document.probe.tag_version is None


@pytest.mark.parametrize("wav_tag_policy", ("id3", "riff_info"))
def test_wav_write_removes_stale_values_from_the_other_tag_scheme(
    wav_tag_policy: str,
    tmp_path: Path,
) -> None:
    _source, staged, _source_hash = _stage(tmp_path, "management_full.wav")
    write_riff_info(
        staged,
        {"INAM": ("Stale RIFF title",), "XTRA": ("Keep RIFF custom",)},
    )
    engine = AudioMetadataEngine()
    snapshot = engine.snapshot(staged)
    plan = engine.plan(
        engine.read(staged),
        DesiredAudioDocument(
            fields=(
                DesiredAudioField(name="title", action="set", value="Unified title"),
            )
        ),
        AudioWritePolicy(wav_tag_policy=wav_tag_policy),
    )

    result = engine.apply(staged, plan)

    assert result.document.metadata.value_for("title") == "Unified title"
    assert read_riff_info(staged)["XTRA"] == ("Keep RIFF custom",)
    if wav_tag_policy == "id3":
        assert "RIFF_INFO:INAM" in plan.scrubbed_raw_keys
        assert "INAM" not in read_riff_info(staged)
        assert "TIT2" in WAVE(staged).tags
    else:
        assert "TIT2" in plan.scrubbed_raw_keys
        assert "TIT2" not in WAVE(staged).tags
        assert read_riff_info(staged)["INAM"] == ("Unified title",)

    restored = engine.restore(staged, snapshot)
    assert restored.document.native_tags == snapshot.native_tags


@pytest.mark.parametrize("audio_format", FORMATS)
def test_typed_artwork_mime_and_image_types_round_trip(
    audio_format: str,
    tmp_path: Path,
) -> None:
    _source, staged, _source_hash = _stage(tmp_path, f"management_full.{audio_format}")
    engine = AudioMetadataEngine()
    snapshot = engine.snapshot(staged)
    artwork = (_artwork("front", "JPEG", (9, 7)),)
    if audio_format != "m4a":
        artwork = (*artwork, _artwork("back", "PNG", (8, 6)))

    plan = engine.plan(
        engine.read(staged),
        DesiredAudioDocument(fields=(), artwork=artwork),
        AudioWritePolicy(),
    )
    result = engine.apply(staged, plan)

    assert sorted(
        (image.image_type, image.mime_type, image.width, image.height)
        for image in result.document.artwork
    ) == sorted(
        (image.image_type, image.mime_type, image.width, image.height)
        for image in artwork
    )
    restored = engine.restore(staged, snapshot)
    assert restored.document.artwork == snapshot.artwork
    assert restored.document.native_tags == snapshot.native_tags


def test_format_cleanup_actions_apply_and_restore(tmp_path: Path) -> None:
    engine = AudioMetadataEngine()

    mp3 = tmp_path / "cleanup.mp3"
    shutil.copy2(FIXTURES / "management_full.mp3", mp3)
    ape = APEv2()
    ape["CUSTOM_APE"] = "remove me"
    ape.save(mp3)
    mp3_snapshot = engine.snapshot(mp3)
    mp3_plan = engine.plan(
        engine.read(mp3),
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(mp3_apev2_policy="remove"),
    )
    engine.apply(mp3, mp3_plan)
    assert engine.read(mp3).native_tags.auxiliary_entries == ()
    engine.restore(mp3, mp3_snapshot)
    assert engine.read(mp3).native_tags == mp3_snapshot.native_tags

    flac = tmp_path / "cleanup.flac"
    shutil.copy2(FIXTURES / "management_full.flac", flac)
    id3 = ID3()
    id3.add(TXXX(encoding=3, desc="CUSTOM_ID3", text=["remove me"]))
    id3.save(flac, v1=0)
    flac_snapshot = engine.snapshot(flac)
    flac_plan = engine.plan(
        engine.read(flac),
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(remove_id3_from_flac=True),
    )
    engine.apply(flac, flac_plan)
    assert engine.read(flac).native_tags.auxiliary_encoded_id3 is None
    engine.restore(flac, flac_snapshot)
    assert engine.read(flac).native_tags == flac_snapshot.native_tags

    aac = tmp_path / "cleanup.aac"
    shutil.copy2(FIXTURES / "management_full.aac", aac)
    aac_snapshot = engine.snapshot(aac)
    aac_plan = engine.plan(
        engine.read(aac),
        DesiredAudioDocument(fields=()),
        AudioWritePolicy(raw_aac_tag_policy="remove_apev2"),
    )
    engine.apply(aac, aac_plan)
    with pytest.raises(APEError):
        APEv2(aac)
    engine.restore(aac, aac_snapshot)
    assert engine.read(aac).native_tags == aac_snapshot.native_tags


@pytest.mark.parametrize("audio_format", FORMATS)
def test_custom_tag_set_append_and_native_restore(
    audio_format: str,
    tmp_path: Path,
) -> None:
    _source, staged, _source_hash = _stage(tmp_path, f"management_full.{audio_format}")
    engine = AudioMetadataEngine()
    snapshot = engine.snapshot(staged)
    desired = DesiredAudioDocument(
        fields=(),
        custom_tags=(
            DesiredCustomTag(name="MOOD", action="set", values=("Warm", "Night")),
            DesiredCustomTag(
                name="CUSTOM_KEEP",
                action="append",
                values=("second value",),
            ),
        ),
    )

    plan = engine.plan(engine.read(staged), desired, AudioWritePolicy())
    result = engine.apply(staged, plan)

    assert plan.blockers == ()
    by_name = {mutation.name: mutation for mutation in plan.custom_tag_mutations}
    raw = {value.key.casefold(): value.values for value in result.document.raw_tags}
    assert raw[by_name["MOOD"].native_key.casefold()] == ("Warm", "Night")
    assert raw[by_name["CUSTOM_KEEP"].native_key.casefold()] == (
        "opaque local value",
        "second value",
    )

    restored = engine.restore(staged, snapshot)
    assert restored.document.native_tags == snapshot.native_tags


def test_riff_custom_tags_require_fourcc_and_id3v23_loss_is_explicit(
    tmp_path: Path,
) -> None:
    _source, riff, _source_hash = _stage(tmp_path, "management_full_riff.wav")
    engine = AudioMetadataEngine()
    valid = engine.plan(
        engine.read(riff),
        DesiredAudioDocument(
            fields=(),
            custom_tags=(
                DesiredCustomTag(name="MOOD", action="set", values=("Warm",)),
            ),
        ),
        AudioWritePolicy(wav_tag_policy="riff_info"),
    )
    result = engine.apply(riff, valid)
    assert read_riff_info(riff)["MOOD"] == ("Warm",)
    assert result.document.probe.tag_version is None

    invalid = engine.plan(
        engine.read(riff),
        DesiredAudioDocument(
            fields=(),
            custom_tags=(
                DesiredCustomTag(name="TOO_LONG", action="set", values=("x",)),
            ),
        ),
        AudioWritePolicy(wav_tag_policy="riff_info"),
    )
    assert any("four-character" in blocker for blocker in invalid.blockers)

    _source, mp3, _source_hash = _stage(tmp_path, "management_full_v23.mp3")
    desired = DesiredAudioDocument(
        fields=(),
        custom_tags=(
            DesiredCustomTag(name="MOOD", action="set", values=("One", "Two")),
        ),
    )
    strict = engine.plan(
        engine.read(mp3),
        desired,
        AudioWritePolicy(id3_version="2.3", id3_text_encoding="utf16"),
    )
    advanced = engine.plan(
        engine.read(mp3),
        desired,
        AudioWritePolicy(
            id3_version="2.3",
            id3_text_encoding="utf16",
            strict_capability_gate=False,
        ),
    )
    assert any("scalar flattening" in blocker for blocker in strict.blockers)
    assert any("scalar flattening" in warning for warning in advanced.warnings)
    assert advanced.custom_tag_mutations[0].after == ("One; Two",)


def test_custom_tag_cannot_alias_managed_native_field() -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / "management_full.flac")

    plan = engine.plan(
        current,
        DesiredAudioDocument(
            fields=(),
            custom_tags=(
                DesiredCustomTag(name="TITLE", action="set", values=("collision",)),
            ),
        ),
        AudioWritePolicy(),
    )

    assert any("managed native tag" in blocker for blocker in plan.blockers)


@pytest.mark.parametrize("audio_format", ("flac", "ogg", "opus", "m4a", "aac"))
def test_synced_lyrics_without_picard_mapping_is_an_explicit_capability_blocker(
    audio_format: str,
) -> None:
    engine = AudioMetadataEngine()
    current = engine.read(FIXTURES / f"management_full.{audio_format}")

    plan = engine.plan(
        current,
        DesiredAudioDocument(
            fields=(
                DesiredAudioField(
                    name="lyrics_synced",
                    action="set",
                    value="[00:01.000]Line",
                ),
            )
        ),
        AudioWritePolicy(),
    )

    assert any("lyrics_synced is not supported" in value for value in plan.blockers)


def test_optional_enrichment_values_survive_an_explicit_unrelated_scrub(
    tmp_path: Path,
) -> None:
    _source, staged, _source_hash = _stage(tmp_path, "management_full.mp3")
    engine = AudioMetadataEngine()
    enrichment = DesiredAudioDocument(
        fields=(
            DesiredAudioField(name="lyrics_plain", action="set", value="Plain"),
            DesiredAudioField(
                name="lyrics_synced", action="set", value="[00:01.000]Synced"
            ),
            DesiredAudioField(name="replaygain_track_gain", action="set", value=3.75),
            DesiredAudioField(
                name="replaygain_track_peak", action="set", value=0.125093
            ),
        )
    )
    engine.apply(
        staged, engine.plan(engine.read(staged), enrichment, AudioWritePolicy())
    )

    scrubbed = engine.apply(
        staged,
        engine.plan(
            engine.read(staged),
            DesiredAudioDocument(fields=()),
            AudioWritePolicy(
                scrub_unmanaged_tags=True,
                preserve_fields=("title",),
            ),
        ),
    )

    assert scrubbed.document.metadata.value_for("lyrics_plain") == "Plain"
    assert scrubbed.document.metadata.value_for("lyrics_synced") == "[00:01.000]Synced"
    assert scrubbed.document.metadata.value_for("replaygain_track_gain") == 3.75
    assert scrubbed.document.metadata.value_for("replaygain_track_peak") == 0.125093


@pytest.mark.parametrize("failure_point", ("_write_vorbis", "_save_audio", "_fsync"))
def test_injected_write_save_and_fsync_failures_are_typed_and_source_is_untouched(
    failure_point: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, staged, source_hash = _stage(tmp_path, "management_full.flac")
    engine = AudioMetadataEngine()
    plan = engine.plan(
        engine.read(staged),
        DesiredAudioDocument(
            fields=(DesiredAudioField(name="title", action="set", value="Failure"),)
        ),
        AudioWritePolicy(),
    )

    def fail(*_args, **_kwargs):
        raise OSError("injected failure")

    monkeypatch.setattr(metadata_writer, failure_point, fail)

    with pytest.raises(AudioWriteError, match="could not be written safely"):
        engine.apply(staged, plan)
    assert _sha256(source) == source_hash


def test_corrupt_written_output_fails_reread_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, staged, source_hash = _stage(tmp_path, "management_full.flac")
    engine = AudioMetadataEngine()
    plan = engine.plan(
        engine.read(staged),
        DesiredAudioDocument(
            fields=(DesiredAudioField(name="title", action="set", value="Corrupt"),)
        ),
        AudioWritePolicy(),
    )
    original_save = metadata_writer._save_audio

    def corrupt_after_save(path, audio, tags, write_plan):
        original_save(path, audio, tags, write_plan)
        path.write_bytes(b"corrupt staged output")

    monkeypatch.setattr(metadata_writer, "_save_audio", corrupt_after_save)

    with pytest.raises(AudioWriteError, match="could not be written safely"):
        engine.apply(staged, plan)
    assert _sha256(source) == source_hash
