"""Integration tests: manifest index — ts-spec-013 §4.5."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder
from tessera.storage.layout import ensure_data_dir, manifest_path
from tessera.storage.manifest_store import ManifestStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _make_manifest(name: str) -> bytes:
    data = tiny()
    builder = ManifestBuilder(
        file_size=len(data),
        tessera_size=TESSERA_SIZE,
        metadata={"name": name},
    )
    builder.add_tessera(hashlib.sha256(data).digest())
    return builder.build()


@pytest.mark.integration
async def test_index_add_and_query(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    hashes = []
    for name in ("alpha.bin", "beta.bin", "gamma.bin"):
        mh = await ms.write(_make_manifest(name))
        hashes.append(mh)

    entries = ms.index.all_metadata()
    assert len(entries) == 3
    names = {meta["name"] for _, meta in entries}
    assert names == {"alpha.bin", "beta.bin", "gamma.bin"}


@pytest.mark.integration
async def test_index_rebuild_from_disk(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    for name in ("a.bin", "b.bin"):
        await ms.write(_make_manifest(name))

    # Clear the in-memory index and rebuild from disk.
    ms.index._index.clear()
    assert ms.index.all_metadata() == []

    await ms.rebuild_index()
    entries = ms.index.all_metadata()
    assert len(entries) == 2


@pytest.mark.integration
async def test_index_remove(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    mh = await ms.write(_make_manifest("removable.bin"))
    assert len(ms.index.all_metadata()) == 1

    ms.index.remove(mh)
    assert ms.index.all_metadata() == []
    # Manifest file still on disk (index is in-memory only).
    mp = manifest_path(tmp_path, mh)
    assert mp.exists()


@pytest.mark.integration
async def test_index_corrupt_manifest(tmp_path: Path) -> None:
    """Corrupt manifest on disk is skipped during rebuild."""
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    mh = await ms.write(_make_manifest("good.bin"))
    await ms.write(_make_manifest("also_good.bin"))

    # Corrupt the first manifest.
    mp = manifest_path(tmp_path, mh)
    mp.write_bytes(b"corrupted garbage data")

    ms.index._index.clear()
    await ms.rebuild_index()

    # Only the intact manifest appears in the index.
    entries = ms.index.all_metadata()
    assert len(entries) == 1
    assert entries[0][1]["name"] == "also_good.bin"
