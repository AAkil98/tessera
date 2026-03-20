"""Integration tests: publish flow — ts-spec-013 §4.1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera.content.chunker import Chunker
from tessera.content.manifest import ManifestBuilder, ManifestParser
from tessera.storage.layout import ensure_data_dir, tessera_dir, tessera_path
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.state import TransferState, write_state
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, empty, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


async def publish(
    data_dir: Path,
    file_data: bytes,
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Simulate a publish: chunk → manifest → store manifest + tesserae."""
    ensure_data_dir(data_dir)
    src = data_dir / "src.bin"
    src.write_bytes(file_data)
    meta = metadata or {"name": "src.bin"}

    chunker = Chunker(tessera_size=TESSERA_SIZE)
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=TESSERA_SIZE,
        metadata=meta,
    )

    ts = TesseraStore(data_dir)
    ms = ManifestStore(data_dir)

    chunks = list(chunker.chunk(src))
    for _idx, _data, leaf_hash in chunks:
        builder.add_tessera(leaf_hash)

    manifest_bytes = builder.build()
    manifest_hash = await ms.write(manifest_bytes)

    for idx, data, _ in chunks:
        await ts.write(manifest_hash, idx, data)

    info = ManifestParser.parse(manifest_bytes)
    state = TransferState.for_seeder(manifest_hash, info.tessera_count)
    await write_state(data_dir, state)

    return manifest_hash


@pytest.mark.integration
async def test_publish_creates_manifest(tmp_path: Path) -> None:
    mh = await publish(tmp_path, small())
    ms = ManifestStore(tmp_path)
    raw = await ms.read(mh)
    assert raw is not None
    info = ManifestParser.parse(raw)
    assert info.tessera_count == 4
    assert info.file_size == len(small())


@pytest.mark.integration
async def test_publish_creates_tesserae(tmp_path: Path) -> None:
    mh = await publish(tmp_path, small())
    for i in range(4):
        p = tessera_path(tmp_path, mh, i)
        assert p.exists(), f"piece {i} missing"
        assert p.stat().st_size == TESSERA_SIZE


@pytest.mark.integration
async def test_publish_tessera_hashes_match_manifest(tmp_path: Path) -> None:
    mh = await publish(tmp_path, small())
    ms = ManifestStore(tmp_path)
    raw = await ms.read(mh)
    assert raw is not None
    info = ManifestParser.parse(raw)
    ts = TesseraStore(tmp_path)
    for i, expected_hash in enumerate(info.leaf_hashes):
        piece = await ts.read(mh, i)
        assert piece is not None
        assert hashlib.sha256(piece).digest() == expected_hash


@pytest.mark.integration
async def test_publish_manifest_hash_determinism(tmp_path: Path) -> None:
    mh1 = await publish(tmp_path, small(), metadata={"name": "f.bin"})
    tmp2 = tmp_path / "run2"
    tmp2.mkdir()
    mh2 = await publish(tmp2, small(), metadata={"name": "f.bin"})
    assert mh1 == mh2


@pytest.mark.integration
async def test_publish_with_metadata(tmp_path: Path) -> None:
    mh = await publish(tmp_path, tiny(), metadata={"name": "f.bin", "tags": "a,b"})
    ms = ManifestStore(tmp_path)
    raw = await ms.read(mh)
    assert raw is not None
    info = ManifestParser.parse(raw)
    assert info.metadata["tags"] == "a,b"


@pytest.mark.integration
async def test_publish_empty_file(tmp_path: Path) -> None:
    mh = await publish(tmp_path, empty())
    ms = ManifestStore(tmp_path)
    raw = await ms.read(mh)
    assert raw is not None
    info = ManifestParser.parse(raw)
    assert info.tessera_count == 0
    assert info.file_size == 0
    td = tessera_dir(tmp_path, mh)
    # Directory may not exist for an empty mosaic.
    if td.exists():
        assert list(td.glob("*.piece")) == []


@pytest.mark.integration
async def test_publish_creates_state_file(tmp_path: Path) -> None:
    from tessera.storage.state import read_state

    mh = await publish(tmp_path, small())
    state = await read_state(tmp_path, mh)
    assert state is not None
    assert state.role == "seeder"
    assert state.tessera_count == 4
    bf = state.get_bitfield()
    assert bf.is_complete()
