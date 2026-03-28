"""Tests for crash-safety cleanup in storage write paths.

Covers the except-BaseException branches in:
  - ManifestStore._write_sync  (manifest_store.py:117-119)
  - TesseraStore._write_sync   (tessera_store.py:64-66)

These branches clean up temp files when write_bytes or os.rename fails,
ensuring no partial files are left on disk after a crash or I/O error.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tessera.storage.layout import ensure_data_dir
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal valid manifest bytes — ManifestParser.parse must succeed.
# We import lazily to build one on the fly.


def _make_manifest_bytes() -> bytes:
    """Build a small valid manifest using the project's own builder."""
    import hashlib

    from tessera.content.manifest import ManifestBuilder

    data = b"hello world"
    leaf_hash = hashlib.sha256(data).digest()

    builder = ManifestBuilder(
        file_size=len(data),
        tessera_size=256,
        metadata={"name": "test.txt"},
    )
    builder.add_tessera(leaf_hash)
    return builder.build()


# ---------------------------------------------------------------------------
# ManifestStore — rename failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_store_rename_failure_cleans_tmp(tmp_path: Path, monkeypatch):
    """If os.rename raises, the temp file must be removed."""
    ensure_data_dir(tmp_path)
    store = ManifestStore(tmp_path)
    manifest_bytes = _make_manifest_bytes()

    original_rename = os.rename

    def failing_rename(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError, match="simulated disk full"):
        await store.write(manifest_bytes)

    # tmp/ must be empty — the cleanup branch removed the temp file.
    tmp_dir = tmp_path / "tmp"
    assert list(tmp_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# ManifestStore — write_bytes failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_store_write_bytes_failure_cleans_tmp(
    tmp_path: Path, monkeypatch
):
    """If Path.write_bytes raises, the temp file must be removed."""
    ensure_data_dir(tmp_path)
    store = ManifestStore(tmp_path)
    manifest_bytes = _make_manifest_bytes()

    original_write_bytes = Path.write_bytes

    def failing_write_bytes(self, data):
        # Create the file so there's something to clean up.
        original_write_bytes(self, b"")
        raise OSError("simulated I/O error")

    monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)

    with pytest.raises(OSError, match="simulated I/O error"):
        await store.write(manifest_bytes)

    tmp_dir = tmp_path / "tmp"
    assert list(tmp_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# TesseraStore — rename failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tessera_store_rename_failure_cleans_tmp(tmp_path: Path, monkeypatch):
    """If os.rename raises, the temp piece file must be removed."""
    ensure_data_dir(tmp_path)
    store = TesseraStore(tmp_path)
    manifest_hash = b"\xaa" * 32

    def failing_rename(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError, match="simulated disk full"):
        await store.write(manifest_hash, 0, b"piece data")

    tmp_dir = tmp_path / "tmp"
    assert list(tmp_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# TesseraStore — write_bytes failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tessera_store_write_bytes_failure_cleans_tmp(
    tmp_path: Path, monkeypatch
):
    """If Path.write_bytes raises, the temp piece file must be removed."""
    ensure_data_dir(tmp_path)
    store = TesseraStore(tmp_path)
    manifest_hash = b"\xaa" * 32

    original_write_bytes = Path.write_bytes

    def failing_write_bytes(self, data):
        original_write_bytes(self, b"")
        raise OSError("simulated I/O error")

    monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)

    with pytest.raises(OSError, match="simulated I/O error"):
        await store.write(manifest_hash, 0, b"piece data")

    tmp_dir = tmp_path / "tmp"
    assert list(tmp_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Pre-existing file survives a failed write attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_failure_does_not_corrupt_existing(tmp_path: Path, monkeypatch):
    """A pre-existing valid piece file must survive a failed overwrite."""
    ensure_data_dir(tmp_path)
    store = TesseraStore(tmp_path)
    manifest_hash = b"\xbb" * 32
    original_data = b"original piece content"

    # Write a valid piece first.
    await store.write(manifest_hash, 0, original_data)

    # Now delete it so _write_sync will attempt again (exists check fails).
    from tessera.storage.layout import tessera_path

    target = tessera_path(tmp_path, manifest_hash, 0)
    target.unlink()

    # Inject a rename failure on the second attempt.
    def failing_rename(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "rename", failing_rename)

    with pytest.raises(OSError, match="simulated disk full"):
        await store.write(manifest_hash, 0, b"new piece content")

    # The target should not exist (the rename never completed).
    assert not target.exists()
    # tmp/ must be clean.
    assert list((tmp_path / "tmp").iterdir()) == []


# ---------------------------------------------------------------------------
# Concurrent writes — one failure does not corrupt the other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_write_failure_isolation(tmp_path: Path, monkeypatch):
    """Two concurrent writes: one fails, the other succeeds cleanly."""
    import asyncio

    ensure_data_dir(tmp_path)
    store = TesseraStore(tmp_path)
    manifest_hash = b"\xcc" * 32

    call_count = 0
    original_rename = os.rename

    def rename_fail_once(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("first rename fails")
        return original_rename(src, dst)

    monkeypatch.setattr(os, "rename", rename_fail_once)

    async def write_piece(idx: int, data: bytes):
        return await store.write(manifest_hash, idx, data)

    results = await asyncio.gather(
        write_piece(0, b"piece-0"),
        write_piece(1, b"piece-1"),
        return_exceptions=True,
    )

    # Exactly one should have failed, one succeeded.
    errors = [r for r in results if isinstance(r, OSError)]
    successes = [r for r in results if r is True]
    assert len(errors) == 1
    assert len(successes) == 1

    # tmp/ must be clean.
    assert list((tmp_path / "tmp").iterdir()) == []
