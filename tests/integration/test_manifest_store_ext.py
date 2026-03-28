"""Integration tests: ManifestStore and ManifestIndex — ts-spec-011 §3."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder
from tessera.storage.layout import ensure_data_dir, manifest_path
from tessera.storage.manifest_store import ManifestIndex, ManifestStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _build_manifest(
    file_data: bytes,
    *,
    tessera_size: int = TESSERA_SIZE,
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Build a valid manifest from *file_data* using ManifestBuilder."""
    meta = metadata or {"name": "test.bin"}
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=tessera_size,
        metadata=meta,
    )
    offset = 0
    while offset < len(file_data):
        chunk = file_data[offset : offset + tessera_size]
        builder.add_tessera(hashlib.sha256(chunk).digest())
        offset += tessera_size
    return builder.build()


# ------------------------------------------------------------------
# ManifestStore tests
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_write_returns_manifest_hash(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(small())
    mh = await ms.write(manifest_bytes)
    assert mh == hashlib.sha256(manifest_bytes).digest()


@pytest.mark.integration
async def test_write_idempotent(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(small())
    mh1 = await ms.write(manifest_bytes)
    mh2 = await ms.write(manifest_bytes)
    assert mh1 == mh2


@pytest.mark.integration
async def test_read_returns_written_bytes(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(small())
    mh = await ms.write(manifest_bytes)
    raw = await ms.read(mh)
    assert raw == manifest_bytes


@pytest.mark.integration
async def test_read_nonexistent_returns_none(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    fake_hash = hashlib.sha256(b"nonexistent").digest()
    result = await ms.read(fake_hash)
    assert result is None


@pytest.mark.integration
async def test_read_detects_corruption(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(tiny())
    mh = await ms.write(manifest_bytes)

    # Corrupt the manifest file on disk.
    mp = manifest_path(tmp_path, mh)
    mp.write_bytes(b"corrupted data that is not a valid manifest")

    result = await ms.read(mh)
    assert result is None


@pytest.mark.integration
async def test_delete_removes_file(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(tiny())
    mh = await ms.write(manifest_bytes)

    mp = manifest_path(tmp_path, mh)
    assert mp.exists()

    await ms.delete(mh)
    assert not mp.exists()


# ------------------------------------------------------------------
# ManifestIndex tests
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_rebuild_index_from_disk(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    await ms.write(_build_manifest(tiny(), metadata={"name": "one.bin"}))
    await ms.write(_build_manifest(small(), metadata={"name": "two.bin"}))

    # Clear the in-memory index and rebuild from disk.
    ms.index._index.clear()
    assert ms.index.all_metadata() == []

    await ms.rebuild_index()
    entries = ms.index.all_metadata()
    assert len(entries) == 2
    names = {meta["name"] for _, meta in entries}
    assert names == {"one.bin", "two.bin"}


@pytest.mark.integration
async def test_index_add_and_query(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    index = ManifestIndex()
    fake_hash = hashlib.sha256(b"fake").digest()
    metadata = {"name": "indexed.bin", "tags": "test"}
    index.add(fake_hash, metadata)

    entries = index.all_metadata()
    assert len(entries) == 1
    assert entries[0] == (fake_hash, metadata)


@pytest.mark.integration
async def test_index_remove(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    index = ManifestIndex()
    fake_hash = hashlib.sha256(b"removable").digest()
    index.add(fake_hash, {"name": "gone.bin"})
    assert len(index.all_metadata()) == 1

    index.remove(fake_hash)
    assert index.all_metadata() == []


@pytest.mark.integration
async def test_delete_removes_from_index(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    manifest_bytes = _build_manifest(tiny(), metadata={"name": "doomed.bin"})
    mh = await ms.write(manifest_bytes)
    assert len(ms.index.all_metadata()) == 1

    await ms.delete(mh)
    assert ms.index.all_metadata() == []
