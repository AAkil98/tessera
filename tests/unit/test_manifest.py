"""Unit tests for ManifestBuilder/Parser — ts-spec-013 §3.6."""

from __future__ import annotations

import hashlib
import struct

import pytest

from tessera.content.manifest import (
    FORMAT_VERSION,
    MAGIC,
    ManifestBuilder,
    ManifestParser,
)
from tessera.content.merkle import build_root
from tessera.errors import ConfigError
from tests.fixtures import DEFAULT_CHUNK_SIZE, empty, exact, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _build_from_data(
    data: bytes,
    tessera_size: int = TESSERA_SIZE,
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Helper: chunk *data* and build a manifest."""
    meta = metadata or {"name": "test.bin"}
    builder = ManifestBuilder(
        file_size=len(data),
        tessera_size=tessera_size,
        metadata=meta,
    )
    offset = 0
    while offset < len(data):
        chunk = data[offset : offset + tessera_size]
        builder.add_tessera(hashlib.sha256(chunk).digest())
        offset += tessera_size
    return builder.build()


@pytest.mark.unit
def test_manifest_roundtrip() -> None:
    """Build → serialize → parse → all fields match."""
    data = small()
    raw = _build_from_data(data)
    info = ManifestParser.parse(raw)

    assert info.tessera_count == 4
    assert info.tessera_size == TESSERA_SIZE
    assert info.file_size == len(data)
    assert info.last_tessera_size == TESSERA_SIZE  # evenly divisible
    assert info.metadata["name"] == "test.bin"
    assert len(info.leaf_hashes) == 4


@pytest.mark.unit
def test_manifest_magic() -> None:
    raw = _build_from_data(tiny())
    assert raw[:4] == b"TSRA"
    assert raw[:4] == MAGIC


@pytest.mark.unit
def test_manifest_format_version() -> None:
    raw = _build_from_data(tiny())
    (version,) = struct.unpack_from("!H", raw, 4)
    assert version == FORMAT_VERSION == 0x0001


@pytest.mark.unit
def test_manifest_metadata_sorted() -> None:
    """Metadata keys must be serialized in sorted order."""
    raw = _build_from_data(tiny(), metadata={"z": "1", "a": "2", "m": "3"})
    info = ManifestParser.parse(raw)
    assert list(info.metadata.keys()) == sorted(info.metadata.keys())
    assert info.metadata["z"] == "1"
    assert info.metadata["a"] == "2"


@pytest.mark.unit
def test_manifest_metadata_max_keys() -> None:
    """65 metadata keys → ConfigError (limit is 64)."""
    meta = {str(i): "v" for i in range(65)}
    with pytest.raises(ConfigError):
        ManifestBuilder(file_size=0, tessera_size=TESSERA_SIZE, metadata=meta)


@pytest.mark.unit
def test_manifest_metadata_max_value() -> None:
    """Value > 1024 bytes → ConfigError."""
    with pytest.raises(ConfigError):
        ManifestBuilder(
            file_size=0,
            tessera_size=TESSERA_SIZE,
            metadata={"k": "x" * 1025},
        )


@pytest.mark.unit
def test_manifest_metadata_len_overflow() -> None:
    """Serialized metadata > 65,535 bytes → error at build time."""
    # Build a metadata dict whose serialized form exceeds the u16 limit.
    # Each entry: 1 + key_len + 2 + val_len. Use a big value string.
    big_val = "x" * 1024
    meta = {str(i): big_val for i in range(64)}
    builder = ManifestBuilder(
        file_size=0,
        tessera_size=TESSERA_SIZE,
        metadata=meta,
        max_metadata_value_bytes=1024 * 2,  # bypass per-value check
    )
    with pytest.raises(ConfigError):
        builder.build()


@pytest.mark.unit
def test_manifest_file_size_consistency() -> None:
    """tessera_count=4, tessera_size=256KiB, last=100KiB → correct file_size."""
    ts = TESSERA_SIZE
    last = 100 * 1024
    file_size = 3 * ts + last
    builder = ManifestBuilder(
        file_size=file_size, tessera_size=ts, metadata={"name": "f"}
    )
    for _ in range(4):
        builder.add_tessera(hashlib.sha256(b"x").digest())
    raw = builder.build()
    info = ManifestParser.parse(raw)
    assert info.file_size == file_size
    assert info.last_tessera_size == last


@pytest.mark.unit
def test_manifest_empty_file() -> None:
    """0 tesserae → root_hash == 0×32, file_size == 0."""
    raw = _build_from_data(empty())
    info = ManifestParser.parse(raw)
    assert info.tessera_count == 0
    assert info.file_size == 0
    assert info.root_hash == b"\x00" * 32
    assert info.leaf_hashes == []


@pytest.mark.unit
def test_manifest_root_hash_recomputed() -> None:
    """Parse manifest, recompute root from leaf_hashes — must match."""
    raw = _build_from_data(small())
    info = ManifestParser.parse(raw)
    recomputed = build_root(info.leaf_hashes)
    assert recomputed == info.root_hash


@pytest.mark.unit
def test_manifest_reject_bad_magic() -> None:
    raw = bytearray(_build_from_data(tiny()))
    raw[0:4] = b"XXXX"
    with pytest.raises(ValueError, match="magic"):
        ManifestParser.parse(bytes(raw))


@pytest.mark.unit
def test_manifest_reject_unknown_version() -> None:
    raw = bytearray(_build_from_data(tiny()))
    struct.pack_into("!H", raw, 4, 0x0002)
    with pytest.raises(ValueError, match="version"):
        ManifestParser.parse(bytes(raw))


@pytest.mark.unit
def test_manifest_hash_determinism() -> None:
    """Same file + tessera_size → identical manifest_hash across runs."""
    data = small()
    raw1 = _build_from_data(data)
    raw2 = _build_from_data(data)
    assert raw1 == raw2
    assert ManifestParser.parse(raw1).manifest_hash == (
        ManifestParser.parse(raw2).manifest_hash
    )


@pytest.mark.unit
def test_manifest_trusted_hash_match() -> None:
    raw = _build_from_data(tiny())
    trusted = hashlib.sha256(raw).digest()
    info = ManifestParser.parse(raw, trusted_hash=trusted)
    assert info.manifest_hash == trusted


@pytest.mark.unit
def test_manifest_trusted_hash_mismatch() -> None:
    raw = _build_from_data(tiny())
    bad_hash = b"\xff" * 32
    with pytest.raises(ValueError, match="mismatch"):
        ManifestParser.parse(raw, trusted_hash=bad_hash)


@pytest.mark.unit
def test_manifest_internal_inconsistency() -> None:
    """Tamper root_hash in header → parser detects Merkle mismatch."""
    raw = bytearray(_build_from_data(small()))
    # root_hash starts at offset 6, is 32 bytes
    raw[6:38] = b"\xde" * 32
    with pytest.raises(ValueError, match="root_hash"):
        ManifestParser.parse(bytes(raw))


@pytest.mark.unit
def test_manifest_single_tessera_exact() -> None:
    """Exactly one tessera (exact.bin = 256 KiB)."""
    data = exact()
    raw = _build_from_data(data)
    info = ManifestParser.parse(raw)
    assert info.tessera_count == 1
    assert info.last_tessera_size == TESSERA_SIZE
    assert info.file_size == len(data)
