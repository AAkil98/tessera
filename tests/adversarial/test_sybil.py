"""Adversarial tests: Sybil resistance — ts-spec-013 §6.4.

A Sybil attacker controls many peer identities that all serve the same
bad data.  The node's per-piece hash verification ensures that no
quantity of identical poisoned responses can produce a successful transfer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import IntegrityError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


class SybilPeerSource:
    """Simulate N Sybil identities all serving the same corrupted piece data.

    The manifest is real; every piece response has its bytes inverted
    (bit-flip attack replicated across all identities).
    """

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        sybil_count: int = 10,
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._sybil_count = sybil_count
        self._call_count = 0

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        # All Sybil identities return the same corrupted bytes.
        self._call_count += 1
        data = await self._ts.read(self._mh, index)
        if data is None:
            return None
        return bytes(b ^ 0xFF for b in data)


class SybilWithOneHonestSource:
    """N-1 Sybil peers serve bad data; exactly one honest peer serves the truth.

    Requests alternate: first N calls are Sybil (corrupt), then the honest
    source is used once per piece.  Because verification is per-piece, the
    honest piece should succeed and the corrupted ones should fail.
    """

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        sybil_count: int = 5,
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._sybil_count = sybil_count
        self._piece_calls: dict[int, int] = {}

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        call_n = self._piece_calls.get(index, 0)
        self._piece_calls[index] = call_n + 1
        if call_n < self._sybil_count:
            # Sybil: corrupted data.
            data = await self._ts.read(self._mh, index)
            return bytes(b ^ 0xFF for b in data) if data else None
        # Honest: real data.
        return await self._ts.read(self._mh, index)


@pytest.mark.asyncio
async def test_sybil_all_corrupt_raises_integrity_error(tmp_path: Path) -> None:
    """When every Sybil peer serves corrupt data, IntegrityError is raised."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = SybilPeerSource(
            seeder._ms, seeder._ts, mh, sybil_count=10
        )
        with pytest.raises(IntegrityError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_sybil_does_not_write_corrupt_pieces_to_disk(tmp_path: Path) -> None:
    """Corrupt pieces from Sybil peers must not be persisted to the tessera store."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = SybilPeerSource(
            seeder._ms, seeder._ts, mh, sybil_count=10
        )
        with pytest.raises(IntegrityError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

        # No piece should be on disk (corrupt data must be rejected before write).
        from tessera.storage.tessera_store import TesseraStore
        from tessera.storage.layout import tessera_dir

        ts = TesseraStore(fetch_dir)
        assert not ts.exists(mh, 0)


@pytest.mark.asyncio
async def test_sybil_majority_cannot_override_hash_check(tmp_path: Path) -> None:
    """Even 100 Sybil identities cannot cause a corrupt piece to pass verification."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = SybilPeerSource(
            seeder._ms, seeder._ts, mh, sybil_count=100
        )
        with pytest.raises(IntegrityError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

        assert not (fetch_dir / "out.bin").exists()
