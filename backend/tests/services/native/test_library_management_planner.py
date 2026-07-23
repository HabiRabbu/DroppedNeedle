import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import msgspec
from PIL import Image
import pytest

from api.v1.schemas.library_management import (
    NamingScriptSettings,
    PICARD_ORGANIZER_PROFILE_ID,
    picard_style_organizer_profile,
    settings_revision,
)
from core.config import Settings
from core.exceptions import StaleRevisionError
from infrastructure.audio.artwork_processor import ArtworkProcessor
from infrastructure.audio.metadata_engine import AudioMetadataEngine
from infrastructure.library_management_blob_store import LibraryManagementBlobStore
from infrastructure.persistence.native_library_store import NativeLibraryStore
from repositories.musicbrainz_management_models import MbManagementRelease
from models.library_management_artwork import ArtworkCandidate
from models.library_management_enrichment import (
    LyricsProjection,
    ReplayGainAnalysis,
    ReplayGainTrackResult,
)
from infrastructure.queue.priority_queue import RequestPriority
from models.audio_metadata import (
    AudioWritePolicy,
    DesiredAudioDocument,
    DesiredAudioField,
)
from services.native.artwork_projection_service import ArtworkProjectionService
from services.native.audio_write_planning_service import AudioWritePlanningService
from services.native.background_workload_gate import BackgroundWorkloadGate
from services.native.canonical_release_metadata_service import (
    CanonicalReleaseMetadataService,
)
from services.native.effective_metadata_projection_service import (
    EffectiveMetadataProjectionService,
)
from services.native.genre_normalizer import GenreNormalizer
from services.native.genre_projection_service import GenreProjectionService
from services.native.library_management_planner import LibraryManagementPlanner
from services.native.library_management_publisher import LibraryManagementPublisher
from services.native.library_management_worker import LibraryManagementWorker
from services.native.library_management_undo_service import LibraryManagementUndoService
from services.native.library_management_baseline_service import (
    LibraryManagementBaselineService,
)
from services.native.library_management_duplicate_service import (
    LibraryManagementDuplicateService,
)
from services.native.library_operation_service import LibraryOperationService
from services.native.library_operation_supervisor import LibraryOperationSupervisor
from services.native.library_policy_resolver import LibraryPolicyResolver
from services.native.naming import NamingTemplateEngine
from services.native.tagging_scripts import TaggingScriptEngine
from services.preferences_service import PreferencesService
from models.library_management_planning import LibraryManagementSelection

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _preferences(tmp_path: Path, root: Path) -> PreferencesService:
    settings = Settings()
    settings.config_file_path = tmp_path / "config.json"
    settings.config_file_path.write_text(
        json.dumps(
            {
                "library_settings": {
                    "library_roots": [
                        {
                            "id": "root-1",
                            "path": str(root),
                            "label": "Music",
                            "policy": "automatic",
                            "rules": [],
                        }
                    ],
                    "staging_path": str(tmp_path / "staging"),
                }
            }
        ),
        encoding="utf-8",
    )
    return PreferencesService(settings)


def _seed_store(database: Path, audio_path: Path) -> NativeLibraryStore:
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO auth_users(id) VALUES ('admin')")
    store = NativeLibraryStore(database, threading.Lock())
    metadata = audio_path.stat()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, normalized_name, kind, created_at, updated_at) "
            "VALUES ('artist-1', 'Alpha', 'alpha', 'alpha', 'group', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, "
            "updated_at) VALUES ('album-1', 'root-1', 'group-1', "
            "'Management Album', 'management album', 'Alpha', 'alpha', 'artist-1', "
            "'automatic', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_tracks "
            "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
            "file_size_bytes, file_mtime_ns, stat_revision, stat_revision_kind, "
            "tag_revision, title, title_folded, artist_name, artist_name_folded, "
            "album_title, album_title_folded, album_artist_name, "
            "album_artist_name_folded, disc_number, track_number, year, genre, "
            "genre_folded, file_format, ingest_source, imported_at, membership_source) "
            "VALUES ('track-1', 'album-1', 'root-1', ?, 'source.flac', ?, ?, ?, ?, "
            "'exact', 'tag-1', 'Management Track', 'management track', 'Alpha', "
            "'alpha', 'Management Album', 'management album', 'Alpha', 'alpha', "
            "1, 2, 2024, 'Electronic', 'electronic', 'flac', 'scan', 1, 'automatic')",
            (
                str(audio_path),
                hashlib.sha256(b"source.flac").hexdigest(),
                metadata.st_size,
                metadata.st_mtime_ns,
                f"{metadata.st_size}:{metadata.st_mtime_ns}",
            ),
        )
        connection.execute(
            "INSERT INTO local_album_external_identities "
            "(local_album_id, provider, release_group_mbid, release_mbid, "
            "decision_source, selected_at) VALUES ('album-1', 'musicbrainz', "
            "'dcff25f1-702d-3b5e-b0da-d48172e6e62a', "
            "'aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b', 'manual', 1)"
        )
        connection.execute(
            "INSERT INTO local_track_external_identities "
            "(local_track_id, provider, recording_mbid, release_mbid, "
            "release_track_mbid, medium_position, release_track_position, "
            "decision_source, selected_at) VALUES ('track-1', 'musicbrainz', "
            "'33333333-3333-4333-8333-333333333333', "
            "'aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b', "
            "'22222222-2222-4222-8222-222222222222', 1, 1, 'manual', 1)"
        )
    return store


def _planner(
    tmp_path: Path,
    store: NativeLibraryStore,
    preferences: PreferencesService,
    workload_gate: BackgroundWorkloadGate | None = None,
    artwork_repository=None,
    lyrics=None,
    replaygain=None,
) -> LibraryManagementPlanner:
    repository = AsyncMock()
    repository.get_canonical_release.return_value = msgspec.json.decode(
        (FIXTURES / "musicbrainz" / "management_release.json").read_bytes(),
        type=MbManagementRelease,
    )
    artwork_repository = artwork_repository or AsyncMock()
    audio = AudioMetadataEngine()
    return LibraryManagementPlanner(
        store,
        preferences,
        CanonicalReleaseMetadataService(store, repository, clock=lambda: 100.0),
        EffectiveMetadataProjectionService(),
        GenreProjectionService(GenreNormalizer(), clock=lambda: 100.0),
        ArtworkProjectionService(artwork_repository, ArtworkProcessor()),
        audio,
        AudioWritePlanningService(audio),
        NamingTemplateEngine(),
        TaggingScriptEngine(),
        LibraryManagementBlobStore(tmp_path / "blobs", store),
        workload_gate,
        lyrics=lyrics,
        replaygain=replaygain,
        clock=lambda: 100.0,
    )


class _ArtworkRepository:
    def __init__(self) -> None:
        output = BytesIO()
        Image.new("RGB", (80, 60), (20, 40, 60)).save(output, format="PNG")
        self.content = output.getvalue()
        self.candidate = ArtworkCandidate(
            candidate_id="exact-front",
            source="cover_art_archive_release",
            locator="https://coverartarchive.org/release/front.png",
            image_types=("front",),
            approved=True,
            primary=True,
            source_is_exact_release=True,
        )

    async def list_management_artwork(
        self,
        *,
        entity_kind: str,
        mbid: str,
        download_size: str,
        priority: RequestPriority,
    ) -> tuple[ArtworkCandidate, ...]:
        del mbid, download_size, priority
        return (self.candidate,) if entity_kind == "release" else ()

    async def download_management_artwork(
        self,
        candidate: ArtworkCandidate,
        *,
        maximum_bytes: int,
        priority: RequestPriority,
    ) -> tuple[bytes, str | None]:
        del candidate, priority
        assert len(self.content) <= maximum_bytes
        return self.content, "image/png"


def _configured(tmp_path: Path, source_setup=None):  # noqa: ANN001
    root = tmp_path / "music"
    root.mkdir()
    source = root / "source.flac"
    shutil.copy2(FIXTURES / "library" / "management_full.flac", source)
    if source_setup is not None:
        source_setup(source)
    preferences = _preferences(tmp_path, root)
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.artwork.embedded_enabled = False
    profile.artwork.external_enabled = False
    profile.genres.sources = ["musicbrainz"]
    profile.organization.move_sidecars = False
    saved = preferences.save_library_management_settings_if_current(
        settings,
        expected_settings_revision=current.settings_revision,
    )
    store = _seed_store(tmp_path / "library.db", source)
    policy_revision = LibraryPolicyResolver(
        preferences.get_typed_library_settings_raw()
    ).policy_revision
    return root, source, preferences, store, saved.settings_revision, policy_revision


@pytest.mark.asyncio
async def test_preview_is_pinned_durable_and_never_mutates_library_files(
    tmp_path: Path,
) -> None:
    (
        root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    planner = _planner(tmp_path, store, preferences)
    before = source.read_bytes()
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="preview-1",
    )
    duplicate = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="preview-1",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )

    assert claimed is not None
    snapshot = await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)
    operation = await store.get_operation_job(handle.job_id)

    assert duplicate.existing is True
    assert duplicate.job_id == handle.job_id
    assert duplicate.preview_token == handle.preview_token
    assert snapshot.phase == "ready"
    assert operation is not None and operation["state"] == "ready"
    assert len(plan) == 1
    assert plan[0].eligibility in {"eligible", "warning"}
    assert plan[0].expected_file_fingerprint == hashlib.sha256(before).hexdigest()
    assert plan[0].destination_relative_path == (
        "Johann Sebastian Bach; Glenn Gould/"
        "Goldberg Variations, BWV 988 (1982)/0101 Aria.flac"
    )
    desired = json.loads(plan[0].desired_document_json)
    assert any(
        value["name"] == "musicbrainz_release_track_id"
        and value["value"] == "22222222-2222-4222-8222-222222222222"
        for value in desired["fields"]
    )
    assert source.read_bytes() == before
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == [
        "source.flac"
    ]


@pytest.mark.asyncio
async def test_preview_pins_exact_plain_lyrics_without_mutating_source(
    tmp_path: Path,
) -> None:
    (
        _root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.lyrics.enabled = True
    profile.enrichment.lyrics.write_synced = False
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    lyrics = AsyncMock()
    lyrics.project.return_value = LyricsProjection(
        status="available",
        plain_lyrics="Pinned lyrics",
        synced_lyrics="[00:01.000]Pinned lyrics",
        provider_id=42,
        provider_revision="lrclib-revision",
    )
    planner = _planner(tmp_path, store, preferences, lyrics=lyrics)
    before = source.read_bytes()

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="lyrics-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    item = (await store.list_library_management_plan_items(handle.job_id))[0]
    desired = json.loads(item.desired_document_json)
    diff = json.loads(item.diff_json)

    assert item.eligibility in {"eligible", "warning"}
    assert any(
        value["name"] == "lyrics_plain" and value["value"] == "Pinned lyrics"
        for value in desired["fields"]
    )
    assert all(value["name"] != "lyrics_synced" for value in desired["fields"])
    assert diff["lyrics_projection"] == {
        "status": "available",
        "provider_id": 42,
        "provider_revision": "lrclib-revision",
        "reason": None,
        "plain_available": True,
        "synced_available": True,
    }
    assert source.read_bytes() == before


@pytest.mark.asyncio
async def test_required_lyrics_failure_blocks_preview_item(tmp_path: Path) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.lyrics.enabled = True
    profile.enrichment.lyrics.required = True
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    lyrics = AsyncMock()
    lyrics.project.return_value = LyricsProjection(
        status="not_found", reason="No exact match."
    )
    planner = _planner(tmp_path, store, preferences, lyrics=lyrics)

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="required-lyrics-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    item = (await store.list_library_management_plan_items(handle.job_id))[0]

    assert item.eligibility == "blocked"
    assert item.reason_code == "METADATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_album_aware_replaygain_values_are_pinned_in_preview(
    tmp_path: Path,
) -> None:
    (
        _root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "replace"
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    replaygain = AsyncMock()
    replaygain.analyze.return_value = ReplayGainAnalysis(
        status="available",
        analyzer_version="loudgain 0.6.8",
        tracks=(
            ReplayGainTrackResult(
                source_path=str(source),
                track_gain_db=3.75,
                track_peak=0.125093,
                album_gain_db=5.7,
                album_peak=0.125093,
            ),
        ),
    )
    planner = _planner(tmp_path, store, preferences, replaygain=replaygain)

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="replaygain-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    item = (await store.list_library_management_plan_items(handle.job_id))[0]
    desired = {
        value["name"]: value["value"]
        for value in json.loads(item.desired_document_json)["fields"]
    }
    diff = json.loads(item.diff_json)

    assert desired["replaygain_track_gain"] == 3.75
    assert desired["replaygain_track_peak"] == 0.125093
    assert desired["replaygain_album_gain"] == 5.7
    assert desired["replaygain_album_peak"] == 0.125093
    assert diff["replaygain_analysis"] == {
        "status": "available",
        "analyzer": "loudgain",
        "analyzer_version": "loudgain 0.6.8",
        "reason": None,
    }
    replaygain.analyze.assert_awaited_once_with((source,), album_aware=True)


@pytest.mark.asyncio
async def test_replaygain_fill_missing_preserves_valid_existing_values(
    tmp_path: Path,
) -> None:
    def seed_replaygain(source: Path) -> None:
        engine = AudioMetadataEngine()
        plan = engine.plan(
            engine.read(source),
            DesiredAudioDocument(
                fields=(
                    DesiredAudioField(
                        name="replaygain_track_gain", action="set", value=9.0
                    ),
                )
            ),
            AudioWritePolicy(),
        )
        engine.apply(source, plan)

    (
        _root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path, source_setup=seed_replaygain)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "fill_missing"
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    replaygain = AsyncMock()
    replaygain.analyze.return_value = ReplayGainAnalysis(
        status="available",
        tracks=(
            ReplayGainTrackResult(
                source_path=str(source),
                track_gain_db=1.25,
                track_peak=0.5,
                album_gain_db=2.5,
                album_peak=0.6,
            ),
        ),
    )
    planner = _planner(tmp_path, store, preferences, replaygain=replaygain)

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="replaygain-fill-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    desired = {
        value["name"]: value["value"]
        for value in json.loads(
            (await store.list_library_management_plan_items(handle.job_id))[
                0
            ].desired_document_json
        )["fields"]
    }

    assert "replaygain_track_gain" not in desired
    assert desired["replaygain_track_peak"] == 0.5
    assert desired["replaygain_album_gain"] == 2.5
    assert desired["replaygain_album_peak"] == 0.6


@pytest.mark.asyncio
async def test_replaygain_preserve_mode_never_runs_analyzer(tmp_path: Path) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "preserve"
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    replaygain = AsyncMock()
    planner = _planner(tmp_path, store, preferences, replaygain=replaygain)

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="replaygain-preserve-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    desired = json.loads(
        (await store.list_library_management_plan_items(handle.job_id))[
            0
        ].desired_document_json
    )

    assert not any(
        value["name"].startswith("replaygain_") for value in desired["fields"]
    )
    replaygain.analyze.assert_not_called()


@pytest.mark.asyncio
async def test_required_replaygain_failure_blocks_entire_album(tmp_path: Path) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.enrichment.replaygain.enabled = True
    profile.enrichment.replaygain.mode = "replace"
    profile.enrichment.replaygain.required = True
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=settings_revision
    )
    replaygain = AsyncMock()
    replaygain.analyze.return_value = ReplayGainAnalysis(
        status="deferred", reason="Analyzer unavailable."
    )
    planner = _planner(tmp_path, store, preferences, replaygain=replaygain)

    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="required-replaygain-preview",
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    await planner.run_claimed_preview(claimed, "worker-1")
    item = (await store.list_library_management_plan_items(handle.job_id))[0]

    assert item.eligibility == "blocked"
    assert item.reason_code == "METADATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_preview_rejects_changed_settings_before_reading_files(
    tmp_path: Path,
) -> None:
    (
        _root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    current = preferences.get_library_management_settings()
    changed = preferences.get_library_management_settings_raw()
    changed.undo_retention_days += 1
    preferences.save_library_management_settings_if_current(
        changed, expected_settings_revision=current.settings_revision
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )

    with pytest.raises(StaleRevisionError, match="settings changed"):
        await planner.run_claimed_preview(claimed, "worker-1")

    assert await store.list_library_management_plan_items(handle.job_id) == []
    assert source.exists()


@pytest.mark.asyncio
async def test_preview_idempotency_key_rejects_a_different_request(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    planner = _planner(tmp_path, store, preferences)
    await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="same-key",
    )

    with pytest.raises(StaleRevisionError, match="different preview request"):
        await planner.create_preview(
            selection=LibraryManagementSelection(kind="albums", ids=("album-1",)),
            profile_id=PICARD_ORGANIZER_PROFILE_ID,
            expected_settings_revision=settings_revision,
            expected_policy_revision=policy_revision,
            actor_user_id="admin",
            idempotency_key="same-key",
        )


@pytest.mark.asyncio
async def test_preview_idempotency_binds_unsaved_activation_settings(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        current_revision,
        policy_revision,
    ) = _configured(tmp_path)
    planner = _planner(tmp_path, store, preferences)
    proposed = preferences.get_library_management_settings_raw()
    proposed.preview_retention_hours += 1
    profile = next(
        value for value in proposed.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="roots", ids=("root-1",)),
        profile_id=profile.id,
        expected_settings_revision=current_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="activation-preview",
        settings_snapshot=proposed,
        effective_profile=profile,
    )
    snapshot = await store.get_library_management_job_snapshot(handle.job_id)

    assert snapshot is not None
    assert snapshot.settings_revision == current_revision
    assert snapshot.proposed_settings_revision == settings_revision(proposed)

    changed_proposal = msgspec.convert(
        msgspec.to_builtins(proposed), type=type(proposed)
    )
    changed_proposal.undo_retention_days += 1
    with pytest.raises(StaleRevisionError, match="different preview request"):
        await planner.create_preview(
            selection=LibraryManagementSelection(kind="roots", ids=("root-1",)),
            profile_id=profile.id,
            expected_settings_revision=current_revision,
            expected_policy_revision=policy_revision,
            actor_user_id="admin",
            idempotency_key="activation-preview",
            settings_snapshot=changed_proposal,
            effective_profile=profile,
        )


@pytest.mark.asyncio
async def test_management_preview_dispatches_through_supervisor_and_defers_for_scan(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    gate = BackgroundWorkloadGate()
    planner = _planner(tmp_path, store, preferences, gate)
    worker = LibraryManagementWorker(
        store,
        planner,
        AsyncMock(spec=LibraryManagementPublisher),
        AsyncMock(spec=LibraryManagementUndoService),
        AsyncMock(spec=LibraryManagementBaselineService),
        AsyncMock(spec=LibraryManagementDuplicateService),
    )
    supervisor = LibraryOperationSupervisor(
        store,
        LibraryOperationService(store),
        AsyncMock(),
        AsyncMock(),
        gate,
        worker,
    )
    first = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="supervised-preview",
    )

    ready = await supervisor.run_once("worker-1", now=100)

    assert ready is not None and ready.id == first.job_id
    assert ready.state == "ready"

    second = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key="scan-race-preview",
    )
    gate.set_scan_active(True)
    assert await supervisor.run_once("worker-2", now=101) is None
    gate.set_scan_active(False)
    claimed = await store.claim_operation_job(
        "worker-2", now=101, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None
    gate.set_scan_active(True)

    deferred = await worker.run_claimed(claimed, "worker-2")

    assert deferred["id"] == second.job_id
    assert deferred["state"] == "queued"
    assert await store.list_library_management_plan_items(second.job_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    [
        ("missing", "FILE_UNREADABLE"),
        ("unreadable", "FILE_UNREADABLE"),
        ("read_only", "ROOT_READ_ONLY"),
        ("out_of_root", "OUT_OF_ROOT"),
        ("symlink", "SYMLINK_UNSUPPORTED"),
    ],
)
async def test_preview_blocks_unsafe_sources(
    tmp_path: Path,
    scenario: str,
    expected_reason: str,
) -> None:
    case = tmp_path / scenario
    case.mkdir()
    (
        root,
        source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(case)
    if scenario == "missing":
        source.unlink()
    elif scenario == "unreadable":
        source.chmod(0o200)
    elif scenario == "read_only":
        root.chmod(0o500)
    elif scenario == "out_of_root":
        with sqlite3.connect(case / "library.db") as connection:
            connection.execute(
                "UPDATE local_tracks SET file_path = ? WHERE id = 'track-1'",
                (str(case / "outside.flac"),),
            )
    elif scenario == "symlink":
        target = case / "outside.flac"
        shutil.copy2(source, target)
        source.unlink()
        source.symlink_to(target)
    planner = _planner(case, store, preferences)
    try:
        handle = await planner.create_preview(
            selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
            profile_id=PICARD_ORGANIZER_PROFILE_ID,
            expected_settings_revision=settings_revision,
            expected_policy_revision=policy_revision,
            actor_user_id="admin",
            idempotency_key=None,
        )
        claimed = await store.claim_operation_job(
            "worker-1", now=100, lease_seconds=60, kind="library_management"
        )
        assert claimed is not None
        await planner.run_claimed_preview(claimed, "worker-1")
        plan = await store.list_library_management_plan_items(handle.job_id)
    finally:
        root.chmod(0o700)
        if source.exists() and not source.is_symlink():
            source.chmod(0o600)

    assert len(plan) == 1
    assert plan[0].eligibility == "blocked"
    assert plan[0].reason_code == expected_reason


@pytest.mark.asyncio
async def test_preview_blocks_destination_collision_without_overwrite(
    tmp_path: Path,
) -> None:
    (
        root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    destination = root / (
        "Johann Sebastian Bach; Glenn Gould/"
        "Goldberg Variations, BWV 988 (1982)/0101 Aria.flac"
    )
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"occupied")
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None

    await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)

    assert plan[0].eligibility == "blocked"
    assert plan[0].reason_code == "PATH_COLLISION_DIFFERENT"
    evidence = json.loads(plan[0].collision_json)
    assert evidence == [
        {
            "classification": "same_path_different_content",
            "existing_relative_path": (
                "Johann Sebastian Bach; Glenn Gould/"
                "Goldberg Variations, BWV 988 (1982)/0101 Aria.flac"
            ),
            "existing_root_id": "root-1",
        }
    ]
    assert destination.read_bytes() == b"occupied"


@pytest.mark.asyncio
async def test_preview_marks_provider_deferral_as_warning(
    tmp_path: Path,
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        _settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.genres.sources = ["musicbrainz", "listenbrainz"]
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None

    await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)

    assert plan[0].eligibility == "warning"
    assert plan[0].reason_code == "OPTIONAL_ENRICHMENT_DEFERRED"


@pytest.mark.asyncio
async def test_preview_blocks_when_destination_has_insufficient_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    monkeypatch.setattr(
        "services.native.library_management_planner.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None

    await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)

    assert plan[0].eligibility == "blocked"
    assert plan[0].reason_code == "INSUFFICIENT_SPACE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity_table", "expected_reason"),
    [
        ("local_album_external_identities", "IDENTITY_NOT_ACCEPTED"),
        ("local_track_external_identities", "TRACK_NOT_MAPPED"),
    ],
)
async def test_preview_requires_accepted_release_and_per_file_mapping(
    tmp_path: Path,
    identity_table: str,
    expected_reason: str,
) -> None:
    (
        _root,
        _source,
        preferences,
        store,
        settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    with sqlite3.connect(tmp_path / "library.db") as connection:
        connection.execute(f"DELETE FROM {identity_table}")
    planner = _planner(tmp_path, store, preferences)
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None

    await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)

    assert plan[0].eligibility == "blocked"
    assert plan[0].reason_code == expected_reason


def test_sidecar_planning_is_album_relative_bounded_and_never_follows_symlinks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    nested = source / "nested"
    nested.mkdir(parents=True)
    destination.mkdir()
    (source / "disc.cue").write_text("FILE track.flac", encoding="utf-8")
    (nested / "nested.cue").write_text("FILE nested.flac", encoding="utf-8")
    (source / "notes.txt").write_text("keep", encoding="utf-8")
    profile = picard_style_organizer_profile()

    planned, reason = LibraryManagementPlanner._sidecars(
        source, destination, profile, True
    )

    assert reason is None
    assert len(planned) == 1
    assert planned[0]["source_relative_path"] == "disc.cue"
    assert planned[0]["destination_relative_path"] == "disc.cue"
    assert planned[0]["byte_size"] == len("FILE track.flac")
    assert planned[0]["sha256"] == hashlib.sha256(b"FILE track.flac").hexdigest()

    (source / "disc.cue").unlink()
    (source / "disc.cue").symlink_to(source / "notes.txt")
    _planned, reason = LibraryManagementPlanner._sidecars(
        source, destination, profile, True
    )
    assert reason == "SIDECAR_COLLISION"


@pytest.mark.asyncio
async def test_preview_materializes_custom_external_artwork_path_without_writing_it(
    tmp_path: Path,
) -> None:
    (
        root,
        _source,
        preferences,
        store,
        _settings_revision,
        policy_revision,
    ) = _configured(tmp_path)
    current = preferences.get_library_management_settings()
    settings = preferences.get_library_management_settings_raw()
    artwork_script = NamingScriptSettings(
        id="6e0e3245-8e5c-4202-acd8-41230c4ca09f",
        name="External artwork",
        source=("{albumartist}/{album}/art-{artwork_type}.{artwork_extension}"),
    )
    settings.naming_scripts.append(artwork_script)
    profile = next(
        value for value in settings.profiles if value.id == PICARD_ORGANIZER_PROFILE_ID
    )
    profile.artwork.embedded_enabled = False
    profile.artwork.external_enabled = True
    profile.artwork.providers = ["cover_art_archive_release"]
    profile.artwork.external_format = "png"
    profile.artwork.external_naming_script_id = artwork_script.id
    saved = preferences.save_library_management_settings_if_current(
        settings, expected_settings_revision=current.settings_revision
    )
    artwork_repository = _ArtworkRepository()
    planner = _planner(
        tmp_path,
        store,
        preferences,
        artwork_repository=artwork_repository,
    )
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    handle = await planner.create_preview(
        selection=LibraryManagementSelection(kind="tracks", ids=("track-1",)),
        profile_id=PICARD_ORGANIZER_PROFILE_ID,
        expected_settings_revision=saved.settings_revision,
        expected_policy_revision=policy_revision,
        actor_user_id="admin",
        idempotency_key=None,
    )
    claimed = await store.claim_operation_job(
        "worker-1", now=100, lease_seconds=60, kind="library_management"
    )
    assert claimed is not None

    await planner.run_claimed_preview(claimed, "worker-1")
    plan = await store.list_library_management_plan_items(handle.job_id)
    choices = json.loads(plan[0].artwork_choices_json)

    assert len(choices) == 1
    assert choices[0]["output_kind"] == "external"
    assert choices[0]["destination_relative_path"] == (
        "Johann Sebastian Bach; Glenn Gould/"
        "Goldberg Variations, BWV 988/art-front.png"
    )
    assert (
        choices[0]["blob_sha256"]
        == hashlib.sha256(artwork_repository.content).hexdigest()
    )
    assert json.loads(plan[0].diff_json)["artwork_changed"] is True
    assert (
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == before
    )
