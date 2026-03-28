"""Adversarial tests: protocol violations — ts-spec-013 §6.3.

A malicious peer can send None for manifest or pieces, truncated data,
or raise exceptions mid-transfer. The node must surface a typed error
(TesseraError or subclass) and never corrupt local storage.
"""

from __future__ import annotations

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


async def _publish(data: bytes, directory: Path) -> tuple[TesseraNode, bytes]:
    """Publish *data* and return the (stopped) seeder node and manifest hash."""
    f = directory / "src.bin"
    f.write_bytes(data)
    async with TesseraNode(_config(directory)) as node:
        mh = await node.publish(f)
    return node, mh


class NullManifestSource:
    """Always returns None for manifest."""

    async def get_manifest(self) -> bytes | None:
        return None

    async def get_piece(self, index: int) -> bytes | None:  # pragma: no cover
        return None


class NullPieceSource:
    """Returns a valid manifest but None for every piece."""

    def __init__(self, ms: ManifestStore, mh: bytes) -> None:
        self._ms = ms
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        return None


class TruncatedPieceSource:
    """Returns a valid manifest but truncates piece data by half."""

    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data is None:
            return None
        return data[: len(data) // 2]  # truncate to half


class ExplodingPieceSource:
    """Returns a valid manifest but raises RuntimeError on piece 1."""

    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        if index == 1:
            raise RuntimeError("simulated network failure")
        return await self._ts.read(self._mh, index)


@pytest.mark.asyncio
async def test_null_manifest_raises(tmp_path: Path) -> None:
    """fetch() must raise TesseraError when the peer returns no manifest."""
    pub = tmp_path / "pub"
    pub.mkdir()
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    seeder, mh = await _publish(small(), pub)

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = NullManifestSource()
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_null_piece_raises(tmp_path: Path) -> None:
    """fetch() must raise TesseraError when the peer returns None for a piece."""
    pub = tmp_path / "pub"
    pub.mkdir()
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    seeder, mh = await _publish(small(), pub)

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = NullPieceSource(seeder._ms, mh)
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_truncated_piece_raises_integrity_error(tmp_path: Path) -> None:
    """A truncated piece must fail hash verification → IntegrityError."""
    pub = tmp_path / "pub"
    pub.mkdir()
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    seeder, mh = await _publish(small(), pub)

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = TruncatedPieceSource(seeder._ms, seeder._ts, mh)
        with pytest.raises(IntegrityError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_peer_exception_propagates_as_tessera_error(tmp_path: Path) -> None:
    """An unexpected exception from get_piece() must surface as a TesseraError."""
    pub = tmp_path / "pub"
    pub.mkdir()
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    seeder, mh = await _publish(small(), pub)

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = ExplodingPieceSource(seeder._ms, seeder._ts, mh)
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_null_manifest_does_not_corrupt_storage(tmp_path: Path) -> None:
    """A failed fetch (null manifest) must leave no partial files in storage."""
    pub = tmp_path / "pub"
    pub.mkdir()
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    seeder, mh = await _publish(tiny(), pub)

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = NullManifestSource()
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

    # No output file should exist.
    assert not (fetch_dir / "out.bin").exists()
