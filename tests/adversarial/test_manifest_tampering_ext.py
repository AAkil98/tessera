"""Adversarial tests: manifest tampering extended (T2) -- ts-spec-013 section 6.2.

Additional scenarios beyond test_manifest_tampering.py:
  - Tampered leaf hash: modify a leaf hash in the binary; content-addressed
    hash check rejects the manifest because SHA-256 no longer matches.
  - Wrong tessera count: source serves a manifest that claims a different
    tessera_count than the real one.
  - Truncated manifest: only the first 10 bytes are served; parser raises.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import TesseraError
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
async def test_tampered_manifest_leaf_hash(tmp_path: Path) -> None:
    """Modify a leaf hash in the manifest binary.

    Because the manifest is content-addressed, SHA-256(tampered_bytes) will
    not equal the trusted manifest hash. The node rejects the manifest
    before it even reaches piece transfer.
    """
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    raw = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw is not None

    # Tamper with a leaf hash -- they start after the 60-byte header + metadata.
    b = bytearray(raw)
    # Flip a byte deep in the leaf-hash region (offset 60 + metadata_len + some bytes).
    # Find a safe offset: the last 32 bytes are always the last leaf hash.
    b[-1] ^= 0xFF
    tampered_bytes = bytes(b)

    # The tampered manifest has a different SHA-256 than `mh`.
    assert hashlib.sha256(tampered_bytes).digest() != mh

    class TamperedLeafSource:
        async def get_manifest(self) -> bytes | None:
            return tampered_bytes

        async def get_piece(self, index: int) -> bytes | None:
            return await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = TamperedLeafSource()  # type: ignore[assignment]
        with pytest.raises(ValueError, match="mismatch"):
            await fetcher.fetch(mh)


@pytest.mark.adversarial
async def test_manifest_wrong_tessera_count(tmp_path: Path) -> None:
    """Source serves a manifest where tessera_count is modified.

    The structural consistency checks or Merkle root verification in
    ManifestParser should reject the manifest (the leaf hash count will
    not match tessera_count). Since the outer hash also changes, the
    fetch rejects it on the content-addressed check.
    """
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())  # 4 chunks

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    raw = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw is not None

    # Modify tessera_count field at offset 38 (4 bytes, big-endian u32).
    import struct

    b = bytearray(raw)
    original_tc = struct.unpack_from("!I", b, 38)[0]
    assert original_tc == 4  # small() produces 4 chunks
    struct.pack_into("!I", b, 38, 8)  # claim 8 tesserae instead of 4
    tampered_bytes = bytes(b)

    # Outer hash no longer matches the trusted manifest hash.
    tampered_hash = hashlib.sha256(tampered_bytes).digest()
    assert tampered_hash != mh

    class WrongCountSource:
        async def get_manifest(self) -> bytes | None:
            return tampered_bytes

        async def get_piece(self, index: int) -> bytes | None:
            return await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = WrongCountSource()  # type: ignore[assignment]
        # Trusted hash is the real `mh`, tampered manifest will fail the
        # content-addressed check (hash mismatch).
        with pytest.raises(ValueError, match="mismatch"):
            await fetcher.fetch(mh)


@pytest.mark.adversarial
async def test_manifest_truncated(tmp_path: Path) -> None:
    """Serve only the first 10 bytes of a manifest.

    ManifestParser.parse() raises ValueError because the data is too short
    to contain even the 60-byte header. The node surfaces this as a
    TesseraError (or ValueError).
    """
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    raw = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw is not None
    truncated = raw[:10]

    class TruncatedManifestSource:
        async def get_manifest(self) -> bytes | None:
            return truncated

        async def get_piece(self, index: int) -> bytes | None:  # pragma: no cover
            return None

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = TruncatedManifestSource()  # type: ignore[assignment]
        # The truncated manifest fails both the hash check and the parser.
        with pytest.raises((ValueError, TesseraError)):
            await fetcher.fetch(mh)
