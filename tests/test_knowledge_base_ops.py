from __future__ import annotations

import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import knowledge_base as kb


def _configure_paths(tmp_path: Path):
    kb.DATA_DIR = tmp_path / "data"
    kb.LIBRARY_DIR = tmp_path / "library"
    kb.UPLOAD_DIR = kb.LIBRARY_DIR
    kb.DEFAULT_BOOK_DIR = kb.LIBRARY_DIR
    kb.LEGACY_UPLOAD_DIR = tmp_path / "uploads"
    kb.LEGACY_BOOK_DIR = tmp_path / "hegel-books"
    kb.MANIFEST_PATH = kb.DATA_DIR / "manifest.json"
    kb.INDEX_PATH = kb.DATA_DIR / "index.json"
    kb._INDEX_CACHE = None
    kb._INDEX_MTIME_NS = -1


def test_deduplicate_manifest_books_by_sha1(tmp_path: Path):
    _configure_paths(tmp_path)
    kb.ensure_dirs()

    p1 = kb.LIBRARY_DIR / "a.txt"
    p2 = kb.LIBRARY_DIR / "b.txt"
    p1.write_text("same content", encoding="utf-8")
    p2.write_text("same content", encoding="utf-8")

    kb.save_manifest(
        [
            kb.DocRecord(id="a", path=str(p1.resolve()), enabled=True),
            kb.DocRecord(id="b", path=str(p2.resolve()), enabled=False),
        ]
    )
    stats = kb.deduplicate_manifest_books()
    assert stats["removed"] == 1
    assert stats["files_deleted"] == 1
    records = kb.load_manifest()
    assert len(records) == 1
    assert records[0].enabled is True


def test_reconcile_library_with_manifest(tmp_path: Path):
    _configure_paths(tmp_path)
    kb.ensure_dirs()

    keep = kb.LIBRARY_DIR / "keep.txt"
    orphan = kb.LIBRARY_DIR / "orphan.txt"
    keep.write_text("keep", encoding="utf-8")
    orphan.write_text("orphan", encoding="utf-8")
    missing = kb.LIBRARY_DIR / "missing.txt"

    kb.save_manifest(
        [
            kb.DocRecord(id="keep", path=str(keep.resolve()), enabled=True),
            kb.DocRecord(id="missing", path=str(missing.resolve()), enabled=True),
        ]
    )
    stats = kb.reconcile_library_with_manifest()
    assert stats["manifest_removed_missing_upload_records"] == 1
    assert stats["library_deleted_orphans"] == 1
    assert keep.exists()
    assert not orphan.exists()

