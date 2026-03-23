"""Integration tests: garbage collection — ts-spec-013 §4.6."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder
from tessera.storage.gc import GarbageCollector
from tessera.storage.layout import (
    ensure_data_dir,
    manifest_path,
    state_path,
    tessera_dir,
)
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.state import TransferState, write_state
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE
_DATA = tiny()
_LEAF = hashlib.sha256(_DATA).digest()


async def _setup_complete_mosaic(
    data_dir: Path, role: str = "fetcher"
) -> bytes:
    """Write a minimal 1-tessera mosaic and state file; return manifest_hash."""
    ensure_data_dir(data_dir)
    builder = ManifestBuilder(
        file_size=len(_DATA),
        tessera_size=TESSERA_SIZE,
        metadata={"name": "f.bin"},
    )
    builder.add_tessera(_LEAF)
    manifest_bytes = builder.build()
    ms = ManifestStore(data_dir)
    mh = await ms.write(manifest_bytes)

    ts = TesseraStore(data_dir)
    await ts.write(mh, 0, _DATA)

    state = (
        TransferState.for_seeder(mh, 1)
        if role == "seeder"
        else TransferState.for_fetcher(mh, 1)
    )
    await write_state(data_dir, state)
    return mh


@pytest.mark.integration
async def test_gc_removes_completed_mosaic(tmp_path: Path) -> None:
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)
    collected = await gc.collect(mh, force=True)
    assert collected is True
    assert not state_path(tmp_path, mh).exists()
    assert not tessera_dir(tmp_path, mh).exists()
    # Manifest retained by default.
    assert manifest_path(tmp_path, mh).exists()


@pytest.mark.integration
async def test_gc_respects_grace_period(tmp_path: Path) -> None:
    """Collect with a future completed_at inside grace period → skipped."""
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)
    collected = await gc.collect(
        mh,
        completed_at=time.time(),  # just now
        grace_period=60.0,
    )
    assert collected is False
    # Data untouched.
    assert tessera_dir(tmp_path, mh).exists()


@pytest.mark.integration
async def test_gc_collects_after_grace_period(tmp_path: Path) -> None:
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)
    old_time = time.time() - 61  # 61 seconds ago
    collected = await gc.collect(mh, completed_at=old_time, grace_period=60.0)
    assert collected is True
    assert not tessera_dir(tmp_path, mh).exists()


@pytest.mark.integration
async def test_gc_does_not_touch_active_seeder(tmp_path: Path) -> None:
    mh = await _setup_complete_mosaic(tmp_path, role="seeder")
    gc = GarbageCollector(tmp_path)
    collected = await gc.collect(mh)  # no force
    assert collected is False
    assert tessera_dir(tmp_path, mh).exists()


@pytest.mark.integration
async def test_gc_retains_manifest_by_default(tmp_path: Path) -> None:
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True, retain_manifests=True)
    assert manifest_path(tmp_path, mh).exists()


@pytest.mark.integration
async def test_gc_deletes_manifest_when_asked(tmp_path: Path) -> None:
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)
    ms = ManifestStore(tmp_path)
    await ms.rebuild_index()
    await gc.collect(
        mh, force=True, retain_manifests=False, manifest_index=ms.index
    )
    assert not manifest_path(tmp_path, mh).exists()
    assert ms.index.all_metadata() == []


@pytest.mark.integration
async def test_gc_cancelled_transfer(tmp_path: Path) -> None:
    """A partial fetcher transfer is eligible for GC."""
    ensure_data_dir(tmp_path)
    builder = ManifestBuilder(
        file_size=len(_DATA),
        tessera_size=TESSERA_SIZE,
        metadata={"name": "partial.bin"},
    )
    builder.add_tessera(_LEAF)
    manifest_bytes = builder.build()
    ms = ManifestStore(tmp_path)
    mh = await ms.write(manifest_bytes)
    ts = TesseraStore(tmp_path)
    await ts.write(mh, 0, _DATA)
    # Only partially completed — fetcher, not done.
    state = TransferState.for_fetcher(mh, 4)
    await write_state(tmp_path, state)

    gc = GarbageCollector(tmp_path)
    collected = await gc.collect(mh, force=True)
    assert collected is True
    assert not state_path(tmp_path, mh).exists()
    assert not tessera_dir(tmp_path, mh).exists()


@pytest.mark.integration
def test_gc_orphaned_directory_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Tessera dir with no state file → warning logged, not auto-deleted."""
    from tessera.storage.layout import startup_cleanup

    ensure_data_dir(tmp_path)
    # Create a tessera directory with no matching state file.
    orphan = tmp_path / "tesserae" / ("ab" * 32)
    orphan.mkdir(parents=True)

    import logging

    with caplog.at_level(logging.WARNING, logger="tessera.storage.layout"):
        startup_cleanup(tmp_path)

    assert orphan.exists()  # not deleted
    assert any("Orphaned" in r.message for r in caplog.records)
