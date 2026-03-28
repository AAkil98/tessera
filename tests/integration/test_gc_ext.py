"""Extended integration tests: garbage collection — ts-spec-013 §4.6.

Complements test_gc.py with finer-grained, single-concern assertions.
"""

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


async def _setup_complete_mosaic(data_dir: Path, role: str = "fetcher") -> bytes:
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


# ------------------------------------------------------------------
# 1. State file removal
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_collect_removes_state_file(tmp_path: Path) -> None:
    """After forced collect the .state file must be gone."""
    mh = await _setup_complete_mosaic(tmp_path)
    sp = state_path(tmp_path, mh)
    assert sp.exists(), "precondition: state file should exist before collect"

    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True)

    assert not sp.exists()


# ------------------------------------------------------------------
# 2. Tessera directory removal
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_collect_removes_tessera_dir(tmp_path: Path) -> None:
    """After forced collect the tessera directory must be gone."""
    mh = await _setup_complete_mosaic(tmp_path)
    td = tessera_dir(tmp_path, mh)
    assert td.exists(), "precondition: tessera dir should exist before collect"

    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True)

    assert not td.exists()


# ------------------------------------------------------------------
# 3. Manifest retained by default
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_collect_retains_manifest_by_default(tmp_path: Path) -> None:
    """Default collect keeps the .manifest file on disk."""
    mh = await _setup_complete_mosaic(tmp_path)
    mp = manifest_path(tmp_path, mh)
    assert mp.exists(), "precondition: manifest should exist before collect"

    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True)

    assert mp.exists()


# ------------------------------------------------------------------
# 4. Manifest deletion when requested
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_collect_deletes_manifest_when_asked(tmp_path: Path) -> None:
    """retain_manifests=False removes the .manifest file."""
    mh = await _setup_complete_mosaic(tmp_path)
    mp = manifest_path(tmp_path, mh)
    assert mp.exists(), "precondition: manifest should exist before collect"

    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True, retain_manifests=False)

    assert not mp.exists()


# ------------------------------------------------------------------
# 5. Grace period respected
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_respects_grace_period(tmp_path: Path) -> None:
    """Collect within the grace window returns False, data untouched."""
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)

    collected = await gc.collect(
        mh,
        completed_at=time.time(),
        grace_period=60.0,
    )

    assert collected is False
    assert state_path(tmp_path, mh).exists()
    assert tessera_dir(tmp_path, mh).exists()


# ------------------------------------------------------------------
# 6. Force overrides grace period
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_force_ignores_grace_period(tmp_path: Path) -> None:
    """force=True collects even when inside the grace window."""
    mh = await _setup_complete_mosaic(tmp_path)
    gc = GarbageCollector(tmp_path)

    collected = await gc.collect(
        mh,
        completed_at=time.time(),
        grace_period=60.0,
        force=True,
    )

    assert collected is True
    assert not tessera_dir(tmp_path, mh).exists()


# ------------------------------------------------------------------
# 7. Active seeder skipped
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_skips_active_seeder(tmp_path: Path) -> None:
    """Seeder-role mosaic is not collected without force."""
    mh = await _setup_complete_mosaic(tmp_path, role="seeder")
    gc = GarbageCollector(tmp_path)

    collected = await gc.collect(mh)

    assert collected is False
    assert tessera_dir(tmp_path, mh).exists()
    assert state_path(tmp_path, mh).exists()


# ------------------------------------------------------------------
# 8. Force overrides seeder protection
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_force_collects_seeder(tmp_path: Path) -> None:
    """force=True collects even when the mosaic has seeder role."""
    mh = await _setup_complete_mosaic(tmp_path, role="seeder")
    gc = GarbageCollector(tmp_path)

    collected = await gc.collect(mh, force=True)

    assert collected is True
    assert not tessera_dir(tmp_path, mh).exists()
    assert not state_path(tmp_path, mh).exists()


# ------------------------------------------------------------------
# 9. Nonexistent mosaic
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_nonexistent_mosaic(tmp_path: Path) -> None:
    """Collecting a hash with no on-disk data returns True (no-op, no error)."""
    ensure_data_dir(tmp_path)
    fake_hash = b"\x00" * 32
    gc = GarbageCollector(tmp_path)

    collected = await gc.collect(fake_hash, force=True)

    assert collected is True


# ------------------------------------------------------------------
# 10. Manifest index updated
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_gc_updates_manifest_index(tmp_path: Path) -> None:
    """When a ManifestIndex is passed, the entry is removed after collect."""
    mh = await _setup_complete_mosaic(tmp_path)

    ms = ManifestStore(tmp_path)
    await ms.rebuild_index()
    index = ms.index
    assert any(h == mh for h, _ in index.all_metadata()), (
        "precondition: hash should be in index"
    )

    gc = GarbageCollector(tmp_path)
    await gc.collect(mh, force=True, manifest_index=index)

    assert all(h != mh for h, _ in index.all_metadata())
