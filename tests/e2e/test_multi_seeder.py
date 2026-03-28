"""E2E tests: multi-seeder scenarios — ts-spec-013 §5.2.

Uses RoundRobinPeerSource to simulate fetching from multiple seeders.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


class RoundRobinPeerSource:
    """Distribute piece requests round-robin across multiple seeders."""

    def __init__(
        self, seeders: list[tuple[ManifestStore, TesseraStore, bytes]]
    ) -> None:
        self._seeders = seeders
        self._idx = 0

    async def get_manifest(self) -> bytes | None:
        ms, _, mh = self._seeders[0]
        return await ms.read(mh)

    async def get_piece(self, index: int) -> bytes | None:
        ms, ts, mh = self._seeders[self._idx % len(self._seeders)]
        self._idx += 1
        return await ts.read(mh, index)


def _config(tmp_path: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=tmp_path, tessera_size=TESSERA_SIZE)


@pytest.mark.e2e
async def test_e2e_three_seeders(tmp_path: Path) -> None:
    """SC2: 3 seeders, 1 fetcher — pieces sourced from all three."""
    data = small()
    # All three seeders publish the same file.
    seeders: list[TesseraNode] = []
    manifest_hash: bytes | None = None
    for i in range(3):
        pub = tmp_path / f"pub{i}"
        src = pub / "small.bin"
        src.parent.mkdir()
        src.write_bytes(data)
        node = TesseraNode(_config(pub))
        await node.start()
        mh = await node.publish(str(src))
        if manifest_hash is None:
            manifest_hash = mh
        assert mh == manifest_hash
        seeders.append(node)

    assert manifest_hash is not None

    # Build round-robin source across all three seeder stores.
    sources = [
        (s._manifest_store, s._tessera_store, manifest_hash)
        for s in seeders
        if s._manifest_store and s._tessera_store
    ]
    provider = RoundRobinPeerSource(sources)  # type: ignore[arg-type]

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        out = await fetcher.fetch(manifest_hash)

    assert out.read_bytes() == data

    for node in seeders:
        await node.stop()


@pytest.mark.e2e
async def test_e2e_seeder_leaves_mid_transfer(tmp_path: Path) -> None:
    """Seeder A serves half the pieces, seeder B serves the rest."""
    data = small()
    total_pieces = 4  # small = 4 × 256 KiB

    class HalfAndHalfSource:
        def __init__(
            self,
            ms: ManifestStore,
            ts_a: TesseraStore,
            ts_b: TesseraStore,
            mh: bytes,
        ) -> None:
            self._ms = ms
            self._ts_a = ts_a
            self._ts_b = ts_b
            self._mh = mh

        async def get_manifest(self) -> bytes | None:
            return await self._ms.read(self._mh)

        async def get_piece(self, index: int) -> bytes | None:
            # First half from seeder A, second half from seeder B.
            ts = self._ts_a if index < total_pieces // 2 else self._ts_b
            return await ts.read(self._mh, index)

    pub_a = tmp_path / "pub_a"
    pub_b = tmp_path / "pub_b"
    for pub in (pub_a, pub_b):
        (pub / "small.bin").parent.mkdir(parents=True)
        (pub / "small.bin").write_bytes(data)

    node_a = TesseraNode(_config(pub_a))
    node_b = TesseraNode(_config(pub_b))
    await node_a.start()
    await node_b.start()
    mh_a = await node_a.publish(str(pub_a / "small.bin"))
    mh_b = await node_b.publish(str(pub_b / "small.bin"))
    assert mh_a == mh_b
    mh = mh_a

    provider = HalfAndHalfSource(
        node_a._manifest_store,  # type: ignore[arg-type]
        node_a._tessera_store,  # type: ignore[arg-type]
        node_b._tessera_store,  # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == data
    await node_a.stop()
    await node_b.stop()
