"""Adversarial tests: manifest tampering (T2) — ts-spec-013 §6.2."""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


@pytest.mark.adversarial
async def test_tampered_manifest_hash(tmp_path: Path) -> None:
    """Peer delivers manifest whose SHA-256 doesn't match the trusted hash."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    class TamperedManifestSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, real_mh: bytes) -> None:
            self._ms, self._ts, self._mh = ms, ts, real_mh

        async def get_manifest(self) -> bytes | None:
            raw = await self._ms.read(self._mh)
            if raw is None:
                return None
            # Tamper: flip a byte in the body (not the header magic).
            b = bytearray(raw)
            b[60] ^= 0xFF
            return bytes(b)

        async def get_piece(self, index: int) -> bytes | None:
            return await self._ts.read(self._mh, index)

    provider = TamperedManifestSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,   # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(ValueError, match="mismatch"):
            await fetcher.fetch(mh)


@pytest.mark.adversarial
async def test_manifest_bad_magic(tmp_path: Path) -> None:
    """Manifest with wrong magic bytes → parser rejects it."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    class BadMagicSource:
        def __init__(self, ts: TesseraStore, mh: bytes) -> None:
            self._ts, self._mh = ts, mh

        async def get_manifest(self) -> bytes | None:
            # Return garbage that won't hash to mh.
            return b"XXXX" + b"\x00" * 60

        async def get_piece(self, index: int) -> bytes | None:
            return await self._ts.read(self._mh, index)

    provider = BadMagicSource(
        publisher._tessera_store,   # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(ValueError):
            await fetcher.fetch(mh)


@pytest.mark.adversarial
async def test_manifest_internal_inconsistency(tmp_path: Path) -> None:
    """Manifest whose root_hash field doesn't match recomputed Merkle root."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    class InconsistentManifestSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
            self._ms, self._ts, self._mh = ms, ts, mh

        async def get_manifest(self) -> bytes | None:
            # Return a manifest that is structurally valid but has a
            # root_hash that doesn't match the leaf hashes.
            # We tamper with root_hash at offset 6 (32 bytes).

            raw = await self._ms.read(self._mh)
            if raw is None:
                return None
            b = bytearray(raw)
            b[6:38] = b"\xde" * 32  # corrupt root_hash
            # We must also update the manifest_hash so it passes the
            # outer hash check — i.e., we don't pass trusted_hash.
            return bytes(b)

        async def get_piece(self, index: int) -> bytes | None:
            return await self._ts.read(self._mh, index)

    # When trusted_hash is provided, the tampered manifest will fail the
    # outer hash check first. Test without trusted_hash to test internal
    # consistency check — this means passing a different manifest_hash.
    import hashlib

    raw_original = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw_original is not None
    b2 = bytearray(raw_original)
    b2[6:38] = b"\xde" * 32
    tampered_bytes = bytes(b2)
    tampered_hash = hashlib.sha256(tampered_bytes).digest()

    class DirectSource:
        async def get_manifest(self) -> bytes | None:
            return tampered_bytes

        async def get_piece(self, index: int) -> bytes | None:
            return await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = DirectSource()  # type: ignore[assignment]
        # fetch() with tampered_hash: outer hash passes, inner check fails
        with pytest.raises(ValueError, match="root_hash"):
            await fetcher.fetch(tampered_hash)
