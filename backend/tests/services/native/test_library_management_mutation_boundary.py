"""Regression guards for the staged Library Management mutation boundary."""

import inspect

from core.dependencies.service_providers import (
    get_download_orchestrator,
    get_download_service,
    get_drop_import_service,
    get_file_processor,
    get_target_drop_import_service,
    get_target_file_processor,
)
from infrastructure.audio.tagger import AudioTagger
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.drop_import_service import DropImportService
from services.native.file_processor import FileProcessor
from services.native.library_scanner import LibraryScanner
from services.native.target_catalog_writer_service import TargetCatalogWriterService


def test_obsolete_scalar_audio_mutators_are_not_public() -> None:
    for name in ("write_mb_tags", "write_album_identity", "write_cover_art"):
        assert not hasattr(AudioTagger, name)
    assert not hasattr(LibraryScanner, "update_track_tags")
    assert not hasattr(TargetCatalogWriterService, "update_tags")
    assert not hasattr(NativeLibraryStore, "update_target_track_tags")


def test_import_services_have_no_legacy_publication_implementation() -> None:
    for name in (
        "_import_into_library",
        "_replace_same_path",
        "_retire_replaced_file",
    ):
        assert not hasattr(FileProcessor, name)
    for name in ("_import_mapped", "_import_bonus", "_move_into_library"):
        assert not hasattr(DropImportService, name)


def test_all_download_and_drop_providers_converge_on_target_publication() -> None:
    assert "return get_target_file_processor()" in inspect.getsource(get_file_processor)
    target_source = inspect.getsource(get_target_file_processor)
    assert "publish_import_bundle=import_library.publish_import_bundle" in target_source
    assert "return get_target_drop_import_service()" in inspect.getsource(
        get_drop_import_service
    )
    target_drop_source = inspect.getsource(get_target_drop_import_service)
    assert (
        "publish_import_bundle=import_library.publish_import_bundle"
        in target_drop_source
    )
    assert "return get_target_download_orchestrator()" in inspect.getsource(
        get_download_orchestrator
    )
    assert "return get_target_download_service()" in inspect.getsource(
        get_download_service
    )
