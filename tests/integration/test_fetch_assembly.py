"""Integration tests: fetch assembly — ts-spec-013 §4.2."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder, ManifestParser
from tessera.errors import IntegrityError
from tessera.storage.layout import ensure_data_dir, tessera_path
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, empty, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


async def _stage_pieces(
    data_dir: Path,
    file_data: bytes,
) -> tuple[bytes, bytes]:
    """Chunk *file_data*, write pieces and manifest; return (manifest_hash, raw_manifest)."""
    ensure_data_dir(data_dir)
    ts = TesseraStore(data_dir)
    ms = ManifestStore(data_dir)
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=TESSERA_SIZE,
        metadata={"name": "test.bin"},
    )
    offset = 0
    idx = 0
    chunks: list[tuple[int, bytes]] = []
    while offset < len(file_data):
        chunk = file_data[offset : offset + TESSERA_SIZE]
        builder.add_tessera(hashlib.sha256(chunk).digest())
        chunks.append((idx, chunk))
        offset += TESSERA_SIZE
        idx += 1
    manifest_bytes = builder.build()
    manifest_hash = await ms.write(manifest_bytes)
    for i, chunk in chunks:
        await ts.write(manifest_hash, i, chunk)
    return manifest_hash, manifest_bytes


@pytest.mark.integration
async def test_assemble_complete_mosaic(tmp_path: Path) -> None:
    data = small()
    mh, manifest_bytes = await _stage_pieces(tmp_path, data)
    info = ManifestParser.parse(manifest_bytes)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    await ts.assemble(mh, info, out)
    assert out.read_bytes() == data


@pytest.mark.integration
async def test_assemble_sequential_read(tmp_path: Path) -> None:
    """Assembler reads in index order regardless of write order."""
    data = small()
    mh, manifest_bytes = await _stage_pieces(tmp_path, data)
    info = ManifestParser.parse(manifest_bytes)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    await ts.assemble(mh, info, out)
    assert out.read_bytes() == data


@pytest.mark.integration
async def test_assemble_single_tessera(tmp_path: Path) -> None:
    mh, manifest_bytes = await _stage_pieces(tmp_path, tiny())
    info = ManifestParser.parse(manifest_bytes)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    await ts.assemble(mh, info, out)
    assert out.read_bytes() == b"\x42"


@pytest.mark.integration
async def test_assemble_empty_mosaic(tmp_path: Path) -> None:
    mh, manifest_bytes = await _stage_pieces(tmp_path, empty())
    info = ManifestParser.parse(manifest_bytes)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    await ts.assemble(mh, info, out)
    assert out.read_bytes() == b""


@pytest.mark.integration
async def test_assemble_detects_corruption(tmp_path: Path) -> None:
    """Corrupt one piece on disk → IntegrityError on assembly."""
    data = small()
    mh, manifest_bytes = await _stage_pieces(tmp_path, data)
    info = ManifestParser.parse(manifest_bytes)
    # Corrupt piece 1 on disk.
    p = tessera_path(tmp_path, mh, 1)
    p.write_bytes(b"\xff" * TESSERA_SIZE)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    with pytest.raises(IntegrityError):
        await ts.assemble(mh, info, out)


@pytest.mark.integration
async def test_assemble_short_last_tessera(tmp_path: Path) -> None:
    """File not divisible by tessera_size → correct output size."""
    size = 500_000
    data = bytes(range(256)) * 2000  # 512_000 bytes — truncate
    data = data[:size]
    mh, manifest_bytes = await _stage_pieces(tmp_path, data)
    info = ManifestParser.parse(manifest_bytes)
    out = tmp_path / "output.bin"
    ts = TesseraStore(tmp_path)
    await ts.assemble(mh, info, out)
    assert out.stat().st_size == size
    assert out.read_bytes() == data
