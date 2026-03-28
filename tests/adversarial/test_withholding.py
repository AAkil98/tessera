"""Adversarial tests: piece withholding — ts-spec-013 §6.5.

A withholding peer advertises a valid manifest and serves most pieces but
deliberately withholds one or more, causing the transfer to stall or fail.
The node must raise a typed error rather than hang indefinitely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import TesseraError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


class WithholdingPeerSource:
    """Serve all pieces except the ones in *withheld_indices*."""

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        withheld_indices: set[int],
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._withheld = withheld_indices

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        if index in self._withheld:
            return None  # withheld
        return await self._ts.read(self._mh, index)


class LastPieceWithheldSource(WithholdingPeerSource):
    """Convenience: withholds only the last piece."""

    def __init__(
        self, ms: ManifestStore, ts: TesseraStore, mh: bytes, total: int
    ) -> None:
        super().__init__(ms, ts, mh, withheld_indices={total - 1})


@pytest.mark.asyncio
async def test_withhold_first_piece_raises(tmp_path: Path) -> None:
    """Withholding piece 0 must cause fetch() to raise TesseraError."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = WithholdingPeerSource(
            seeder._ms, seeder._ts, mh, withheld_indices={0}
        )
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_withhold_last_piece_raises(tmp_path: Path) -> None:
    """Withholding the final piece must cause fetch() to raise TesseraError."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = LastPieceWithheldSource(
            seeder._ms,
            seeder._ts,
            mh,
            total=4,  # small() has 4 pieces
        )
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_withhold_middle_piece_raises(tmp_path: Path) -> None:
    """Withholding a middle piece must cause fetch() to raise TesseraError."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = WithholdingPeerSource(
            seeder._ms, seeder._ts, mh, withheld_indices={2}
        )
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")


@pytest.mark.asyncio
async def test_withhold_does_not_produce_output_file(tmp_path: Path) -> None:
    """A failed transfer due to withholding must not leave a partial output file."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    out_path = fetch_dir / "out.bin"

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = WithholdingPeerSource(
            seeder._ms, seeder._ts, mh, withheld_indices={1}
        )
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=out_path)

    assert not out_path.exists()


@pytest.mark.asyncio
async def test_withhold_all_pieces_raises(tmp_path: Path) -> None:
    """Withholding every piece must cause fetch() to raise TesseraError immediately."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = WithholdingPeerSource(
            seeder._ms, seeder._ts, mh, withheld_indices={0, 1, 2, 3}
        )
        with pytest.raises(TesseraError):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")
