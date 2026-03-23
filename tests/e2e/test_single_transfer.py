"""E2E tests: single seeder → single leecher — ts-spec-013 §5.1.

These tests exercise the complete publish→fetch→assemble pipeline using
an in-process LocalPeerSource in place of MFP channels.  All data-path
logic (chunking, manifest building, piece verification, assembly,
whole-file integrity) is fully exercised.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, exact, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# LocalPeerSource — in-process substitute for MFP channels
# ---------------------------------------------------------------------------


class LocalPeerSource:
    """Serve manifest and pieces from another TesseraNode's storage."""

    def __init__(
        self,
        manifest_store: ManifestStore,
        tessera_store: TesseraStore,
        manifest_hash: bytes,
    ) -> None:
        self._ms = manifest_store
        self._ts = tessera_store
        self._mh = manifest_hash

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts.read(self._mh, index)


def _local_source(seeder: TesseraNode, manifest_hash: bytes) -> LocalPeerSource:
    assert seeder._manifest_store is not None
    assert seeder._tessera_store is not None
    return LocalPeerSource(
        seeder._manifest_store, seeder._tessera_store, manifest_hash
    )


def _config(tmp_path: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=tmp_path, tessera_size=TESSERA_SIZE)


# ---------------------------------------------------------------------------
# SC5: 20-line publish → discover → fetch cycle
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_sc5_twenty_line_cycle(tmp_path: Path) -> None:
    """SC5: complete cycle expressible in ≤ 20 lines of application code."""
    pub_dir = tmp_path / "pub"
    fet_dir = tmp_path / "fet"
    src = pub_dir / "report.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(TesseraConfig(data_dir=pub_dir, tessera_size=TESSERA_SIZE)) as publisher:
        manifest_hash = await publisher.publish(str(src), metadata={"description": "test file"})

    async with TesseraNode(TesseraConfig(data_dir=fet_dir, tessera_size=TESSERA_SIZE)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, manifest_hash)  # type: ignore[assignment]
        out = await fetcher.fetch(manifest_hash)

    assert out.read_bytes() == src.read_bytes()


# ---------------------------------------------------------------------------
# §5.1 single seeder, single leecher
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_basic_transfer(tmp_path: Path) -> None:
    """Publisher publishes small.bin; fetcher output is byte-identical."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == src.read_bytes()
    assert hashlib.sha256(out.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()


@pytest.mark.e2e
async def test_e2e_metadata_preserved(tmp_path: Path) -> None:
    """Metadata survives the publish→fetch round trip."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "file.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(
            str(src), metadata={"description": "test", "tags": "a,b"}
        )

    async with TesseraNode(_config(fet)) as fetcher:
        from tessera.content.manifest import ManifestParser

        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        await fetcher.fetch(mh)
        raw = await fetcher._manifest_store.read(mh)
        assert raw is not None
        info = ManifestParser.parse(raw)
        assert info.metadata["description"] == "test"
        assert info.metadata["tags"] == "a,b"


@pytest.mark.e2e
async def test_e2e_tiny_file(tmp_path: Path) -> None:
    """1-byte file transfers correctly."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "tiny.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == b"\x42"


@pytest.mark.e2e
async def test_e2e_empty_file(tmp_path: Path) -> None:
    """0-byte file: manifest exchanged, no pieces transferred, output is empty."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "empty.bin"
    src.parent.mkdir()
    src.write_bytes(b"")

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == b""


@pytest.mark.e2e
async def test_e2e_exact_boundary(tmp_path: Path) -> None:
    """File exactly one tessera in size."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "exact.bin"
    src.parent.mkdir()
    src.write_bytes(exact())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.stat().st_size == TESSERA_SIZE


@pytest.mark.e2e
async def test_e2e_transfer_status(tmp_path: Path) -> None:
    """on_progress callback is invoked; TransferStatus fields are valid."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    progress_events = []

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        await fetcher.fetch(mh, on_progress=progress_events.append)

    assert len(progress_events) >= 1
    last = progress_events[-1]
    assert last.tesserae_verified == last.tesserae_total
    assert last.progress == pytest.approx(1.0)


@pytest.mark.e2e
async def test_e2e_on_manifest_created_callback(tmp_path: Path) -> None:
    """on_manifest_created fires once with correct fields."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    events = []

    async with TesseraNode(_config(pub)) as publisher:
        publisher.on_manifest_created = events.append
        mh = await publisher.publish(str(src))

    assert len(events) == 1
    assert events[0].manifest_hash == mh
    assert events[0].tessera_count == 4  # small = 4 × 256 KiB


@pytest.mark.e2e
async def test_e2e_on_transfer_complete_callback(tmp_path: Path) -> None:
    """on_transfer_complete fires exactly once after successful fetch."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    events = []

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher.on_transfer_complete = events.append
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        await fetcher.fetch(mh)

    assert len(events) == 1
    ev = events[0]
    assert ev.manifest_hash == mh
    assert ev.file_size == len(small())
    assert ev.peers_used == 1


@pytest.mark.e2e
async def test_e2e_cancel(tmp_path: Path) -> None:
    """cancel() transitions swarm to CLOSED."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    from tessera.types import SwarmState

    async with TesseraNode(_config(pub)) as node:
        mh = await node.publish(str(src))
        assert node._registry.get(mh).state == SwarmState.ACTIVE
        await node.cancel(mh)
        assert node._registry.get(mh).state == SwarmState.CLOSED
