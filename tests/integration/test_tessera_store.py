"""Integration tests: TesseraStore — ts-spec-011 §4, §6."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder, ManifestParser
from tessera.errors import IntegrityError
from tessera.storage.layout import ensure_data_dir, tessera_dir, tessera_path
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _stage_manifest(
    file_data: bytes,
    *,
    tessera_size: int = TESSERA_SIZE,
) -> tuple[bytes, list[tuple[int, bytes]]]:
    """Build a manifest and return (manifest_bytes, [(index, chunk), ...])."""
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=tessera_size,
        metadata={"name": "test.bin"},
    )
    offset = 0
    idx = 0
    chunks: list[tuple[int, bytes]] = []
    while offset < len(file_data):
        chunk = file_data[offset : offset + tessera_size]
        builder.add_tessera(hashlib.sha256(chunk).digest())
        chunks.append((idx, chunk))
        offset += tessera_size
        idx += 1
    return builder.build(), chunks


# ------------------------------------------------------------------
# Write / Read basics
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_write_creates_piece_file(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"manifest").digest()
    data = b"\xab" * 256
    await ts.write(mh, 0, data)
    p = tessera_path(tmp_path, mh, 0)
    assert p.exists()


@pytest.mark.integration
async def test_write_returns_true_first_false_second(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"manifest").digest()
    data = b"\xcd" * 128
    first = await ts.write(mh, 0, data)
    second = await ts.write(mh, 0, data)
    assert first is True
    assert second is False


@pytest.mark.integration
async def test_read_returns_written_bytes(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"manifest").digest()
    data = b"\xef" * 512
    await ts.write(mh, 0, data)
    result = await ts.read(mh, 0)
    assert result == data


@pytest.mark.integration
async def test_read_nonexistent_returns_none(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"missing").digest()
    result = await ts.read(mh, 99)
    assert result is None


# ------------------------------------------------------------------
# Exists
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_exists_true_after_write(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"manifest").digest()
    await ts.write(mh, 0, b"\x01" * 64)
    assert ts.exists(mh, 0) is True


@pytest.mark.integration
async def test_exists_false_before_write(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"nothing").digest()
    assert ts.exists(mh, 0) is False


# ------------------------------------------------------------------
# Count
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_count_matches_written_pieces(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"three-pieces").digest()
    for i in range(3):
        await ts.write(mh, i, f"piece-{i}".encode())
    count = await ts.count(mh)
    assert count == 3


@pytest.mark.integration
async def test_count_zero_for_unknown_mosaic(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"unknown").digest()
    count = await ts.count(mh)
    assert count == 0


# ------------------------------------------------------------------
# Bitfield rebuild
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_rebuild_bitfield_matches_disk(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"sparse").digest()

    # Write pieces 0 and 2, skip piece 1.
    await ts.write(mh, 0, b"chunk-0")
    await ts.write(mh, 2, b"chunk-2")

    bf = await ts.rebuild_bitfield(mh, tessera_count=3)
    assert bf.get(0) is True
    assert bf.get(1) is False
    assert bf.get(2) is True
    assert bf.count_set() == 2


# ------------------------------------------------------------------
# Assembly
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_assemble_correct_output(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    file_data = small()
    manifest_bytes, chunks = _stage_manifest(file_data)
    mh = hashlib.sha256(manifest_bytes).digest()
    info = ManifestParser.parse(manifest_bytes)

    ts = TesseraStore(tmp_path)
    from tessera.storage.manifest_store import ManifestStore

    ms = ManifestStore(tmp_path)
    await ms.write(manifest_bytes)

    for idx, chunk in chunks:
        await ts.write(mh, idx, chunk)

    out = tmp_path / "assembled.bin"
    await ts.assemble(mh, info, out)
    assert out.read_bytes() == file_data


@pytest.mark.integration
async def test_assemble_detects_corrupt_piece(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    file_data = small()
    manifest_bytes, chunks = _stage_manifest(file_data)
    mh = hashlib.sha256(manifest_bytes).digest()
    info = ManifestParser.parse(manifest_bytes)

    ts = TesseraStore(tmp_path)
    for idx, chunk in chunks:
        await ts.write(mh, idx, chunk)

    # Corrupt piece 1 on disk.
    p = tessera_path(tmp_path, mh, 1)
    p.write_bytes(b"\xff" * TESSERA_SIZE)

    out = tmp_path / "output.bin"
    with pytest.raises(IntegrityError):
        await ts.assemble(mh, info, out)


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_mosaic_removes_directory(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"deletable").digest()
    await ts.write(mh, 0, b"data")
    await ts.write(mh, 1, b"more")

    td = tessera_dir(tmp_path, mh)
    assert td.exists()

    await ts.delete_mosaic(mh)
    assert not td.exists()


# ------------------------------------------------------------------
# Concurrency
# ------------------------------------------------------------------


@pytest.mark.integration
async def test_concurrent_writes(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = hashlib.sha256(b"concurrent").digest()

    async def do_write(index: int) -> bool:
        return await ts.write(mh, index, f"piece-{index}".encode())

    results = await asyncio.gather(*(do_write(i) for i in range(10)))
    assert all(r is True for r in results)
    count = await ts.count(mh)
    assert count == 10
