"""Adversarial tests: discovery poisoning — ts-spec-013 §6.6.

A poisoned discovery source returns a manifest hash that does not match
the bytes it serves.  The node must reject it via hash verification and
raise IntegrityError rather than storing or assembling the bad data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import IntegrityError, TesseraError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


class PoisonedManifestHashSource:
    """Serve a valid manifest but claim a different (poisoned) hash.

    The caller requests using *fake_hash*; we serve the real manifest bytes
    whose SHA-256 is *real_hash*.  ManifestParser.parse(trusted_hash=fake_hash)
    must reject this.
    """

    def __init__(self, ms: ManifestStore, ts: TesseraStore, real_mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._real_mh = real_mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._real_mh)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts.read(self._real_mh, index)


class RandomManifestSource:
    """Serve random bytes as the manifest."""

    async def get_manifest(self) -> bytes | None:
        return os.urandom(128)

    async def get_piece(self, index: int) -> bytes | None:  # pragma: no cover
        return os.urandom(TESSERA_SIZE)


class SwappedManifestSource:
    """Serve manifest B when asked about manifest A."""

    def __init__(
        self,
        ms_b: ManifestStore,
        ts_b: TesseraStore,
        mh_b: bytes,
    ) -> None:
        self._ms_b = ms_b
        self._ts_b = ts_b
        self._mh_b = mh_b

    async def get_manifest(self) -> bytes | None:
        return await self._ms_b.read(self._mh_b)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts_b.read(self._mh_b, index)


@pytest.mark.asyncio
async def test_wrong_manifest_hash_raises(tmp_path: Path) -> None:
    """Requesting with a fake hash while receiving a different manifest raises."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        real_mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    # Create a fake hash (all zeros — guaranteed not to match).
    fake_mh = b"\x00" * 32

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = PoisonedManifestHashSource(
            seeder._ms, seeder._ts, real_mh
        )
        with pytest.raises((IntegrityError, TesseraError, ValueError)):
            await leecher.fetch(fake_mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_random_manifest_bytes_raises(tmp_path: Path) -> None:
    """Random bytes served as a manifest must cause a parse/integrity failure."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(tiny())

    async with TesseraNode(_config(pub)) as seeder:
        real_mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = RandomManifestSource()
        with pytest.raises((IntegrityError, TesseraError, Exception)):
            await leecher.fetch(real_mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_swapped_manifest_raises(tmp_path: Path) -> None:
    """Receiving manifest B when requesting manifest A must be rejected."""
    pub_a = tmp_path / "pub_a"
    pub_b = tmp_path / "pub_b"
    pub_a.mkdir()
    pub_b.mkdir()

    (pub_a / "a.bin").write_bytes(small(seed=1))
    (pub_b / "b.bin").write_bytes(small(seed=2))

    async with TesseraNode(_config(pub_a)) as seeder_a:
        mh_a = await seeder_a.publish(pub_a / "a.bin")

    async with TesseraNode(_config(pub_b)) as seeder_b:
        mh_b = await seeder_b.publish(pub_b / "b.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    async with TesseraNode(_config(fetch_dir)) as leecher:
        # Request mh_a but receive seeder_b's manifest.
        leecher._test_piece_provider = SwappedManifestSource(
            seeder_b._ms, seeder_b._ts, mh_b
        )
        with pytest.raises((IntegrityError, TesseraError, ValueError)):
            await leecher.fetch(mh_a, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_poisoned_discovery_does_not_write_output(tmp_path: Path) -> None:
    """A discovery-poisoned transfer must not produce an output file."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        real_mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    fake_mh = b"\xff" * 32
    out_path = fetch_dir / "out.bin"

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = PoisonedManifestHashSource(
            seeder._ms, seeder._ts, real_mh
        )
        with pytest.raises((IntegrityError, TesseraError, ValueError)):
            await leecher.fetch(fake_mh, output_path=out_path)

    assert not out_path.exists()
