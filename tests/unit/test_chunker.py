"""Unit tests for Chunker — ts-spec-013 §3.1."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera.content.chunker import Chunker, FixedSizeChunking
from tessera.errors import ConfigError
from tests.fixtures import (
    DEFAULT_CHUNK_SIZE,
    empty,
    exact,
    small,
    tiny,
)

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _write(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "file.bin"
    p.write_bytes(data)
    return p


@pytest.mark.unit
def test_chunk_small_file(tmp_path: Path) -> None:
    """1 MiB file → 4 tesserae of 256 KiB each."""
    data = small()
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    chunks = list(chunker.chunk(f))
    assert len(chunks) == 4
    for idx, chunk_data, _ in chunks:
        assert len(chunk_data) == TESSERA_SIZE
        assert idx == chunks.index((idx, chunk_data, _))


@pytest.mark.unit
def test_chunk_exact_boundary(tmp_path: Path) -> None:
    """File exactly one tessera → 1 tessera, no short final piece."""
    data = exact()
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    chunks = list(chunker.chunk(f))
    assert len(chunks) == 1
    assert len(chunks[0][1]) == TESSERA_SIZE


@pytest.mark.unit
def test_chunk_single_byte(tmp_path: Path) -> None:
    """1-byte file → 1 tessera of 1 byte."""
    f = _write(tmp_path, tiny())
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    chunks = list(chunker.chunk(f))
    assert len(chunks) == 1
    assert chunks[0][1] == b"\x42"


@pytest.mark.unit
def test_chunk_empty_file(tmp_path: Path) -> None:
    """0-byte file → 0 tesserae."""
    f = _write(tmp_path, empty())
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    chunks = list(chunker.chunk(f))
    assert chunks == []
    assert chunker.tessera_count(f) == 0


@pytest.mark.unit
def test_chunk_not_divisible(tmp_path: Path) -> None:
    """500,000 bytes → 2 tesserae: 256 KiB + remainder."""
    size = 500_000
    data = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    chunks = list(chunker.chunk(f))
    assert len(chunks) == 2
    assert len(chunks[0][1]) == TESSERA_SIZE
    last_size = size - TESSERA_SIZE
    assert len(chunks[1][1]) == last_size
    assert chunker.last_tessera_size(f) == last_size


@pytest.mark.unit
def test_chunk_determinism(tmp_path: Path) -> None:
    """Same file, two runs → identical sequences and leaf hashes."""
    data = small()
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    run1 = list(chunker.chunk(f))
    run2 = list(chunker.chunk(f))
    assert run1 == run2


@pytest.mark.unit
def test_chunk_leaf_hashes(tmp_path: Path) -> None:
    """Each tessera's leaf_hash == SHA-256(data)."""
    data = small()
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=TESSERA_SIZE)
    for _idx, chunk_data, leaf_hash in chunker.chunk(f):
        assert leaf_hash == hashlib.sha256(chunk_data).digest()


@pytest.mark.unit
def test_chunk_tessera_size_constraint() -> None:
    """tessera_size > max_payload_size - 5 → ConfigError."""
    with pytest.raises(ConfigError):
        Chunker(tessera_size=1_048_572, max_payload_size=1_048_576)


@pytest.mark.unit
def test_chunk_zero_tessera_size() -> None:
    with pytest.raises(ConfigError):
        Chunker(tessera_size=0)


@pytest.mark.unit
def test_chunk_custom_tessera_size(tmp_path: Path) -> None:
    """1 MiB file at 128 KiB tessera_size → 8 tesserae."""
    data = small()
    f = _write(tmp_path, data)
    chunker = Chunker(tessera_size=128 * 1024)
    chunks = list(chunker.chunk(f))
    assert len(chunks) == 8


@pytest.mark.unit
def test_chunk_strategy_protocol() -> None:
    """FixedSizeChunking satisfies the ChunkingStrategy protocol."""
    from tessera.content.chunker import ChunkingStrategy

    assert isinstance(FixedSizeChunking(), ChunkingStrategy)
