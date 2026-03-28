"""Adversarial tests: piece poisoning (T1) — ts-spec-013 §6.1.

SC3: A peer that serves corrupted data is detected and the transfer fails
with IntegrityError. The hash of the received data does not match the
manifest's leaf hash for that index.
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


class PoisonedPeerSource:
    """Serve a valid manifest but corrupted piece data."""

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        corrupt_index: int = 0,
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._corrupt = corrupt_index

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data is not None and index == self._corrupt:
            # Flip every byte — clearly wrong data.
            return bytes(b ^ 0xFF for b in data)
        return data


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


@pytest.mark.adversarial
async def test_poison_single_piece(tmp_path: Path) -> None:
    """SC3: poisoned piece → IntegrityError; transfer does not complete."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    provider = PoisonedPeerSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,  # type: ignore[arg-type]
        mh,
        corrupt_index=0,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(IntegrityError) as exc_info:
            await fetcher.fetch(mh)

    err = exc_info.value
    assert err.manifest_hash == mh
    assert len(err.expected) == 32
    assert len(err.actual) == 32
    assert err.expected != err.actual


@pytest.mark.adversarial
async def test_poison_correct_hash_wrong_index(tmp_path: Path) -> None:
    """Peer serves piece index 0's data in response to request for index 1."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    class WrongIndexSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
            self._ms, self._ts, self._mh = ms, ts, mh

        async def get_manifest(self) -> bytes | None:
            return await self._ms.read(self._mh)

        async def get_piece(self, index: int) -> bytes | None:
            # Always return piece 0 regardless of which index is requested.
            return await self._ts.read(self._mh, 0)

    provider = WrongIndexSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,  # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(IntegrityError):
            await fetcher.fetch(mh)
