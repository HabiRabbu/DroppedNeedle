"""Phase 2 gate: the old integration code is deleted.

Phase 1 brownout-stubbed the directory but left the `.py` files on disk; Phase 2
removes them. The directory itself is kept (with only ``__init__.py``) for git
history. This test inverts the Phase 1 guard: it asserts nothing but the empty
``__init__.py`` marker remains.
"""

from pathlib import Path


def test_lidarr_repository_directory_holds_only_empty_init():
    lidarr_dir = Path(__file__).resolve().parents[2] / "repositories" / "lidarr"
    assert lidarr_dir.is_dir()

    py_files = sorted(p.name for p in lidarr_dir.glob("*.py"))
    assert py_files == ["__init__.py"]

    init_source = (lidarr_dir / "__init__.py").read_text()
    assert "import" not in init_source
    assert "__all__" not in init_source
