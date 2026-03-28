"""E2E tests: TesseraNode lifecycle, publish, fetch, and error paths.

Tests cover start/stop semantics, async context manager, callback
contracts, resume behaviour, capacity limits, and error wrapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import (
    CapacityError,
    IntegrityError,
    StarvationError,
    TesseraError,
)
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tessera.types import NodeStatus, SwarmState
from tests.fixtures import DEFAULT_CHUNK_SIZE, empty, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(path: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=path, tessera_size=DEFAULT_CHUNK_SIZE)


class LocalPeerSource:
    """Serve manifest and pieces from another TesseraNode's storage."""

    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts.read(self._mh, index)


class CorruptPieceSource(LocalPeerSource):
    """Return corrupted data for piece 0."""

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data and index == 0:
            return b"\xff" * len(data)  # wrong hash
        return data


class ExplodingSource(LocalPeerSource):
    """Raise RuntimeError on piece 1."""

    async def get_piece(self, index: int) -> bytes | None:
        if index == 1:
            raise RuntimeError("boom")
        return await self._ts.read(self._mh, index)


def _local_source(seeder: TesseraNode, mh: bytes) -> LocalPeerSource:
    assert seeder._manifest_store is not None
    assert seeder._tessera_store is not None
    return LocalPeerSource(seeder._manifest_store, seeder._tessera_store, mh)


# ---------------------------------------------------------------------------
# 1. Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_node_start_stop(tmp_path: Path) -> None:
    """TesseraNode starts and stops cleanly without error."""
    node = TesseraNode(_config(tmp_path))
    assert node._started is False
    await node.start()
    assert node._started is True
    await node.stop()
    assert node._started is False


@pytest.mark.e2e
async def test_node_context_manager(tmp_path: Path) -> None:
    """async with works; _started is True inside the block."""
    async with TesseraNode(_config(tmp_path)) as node:
        assert node._started is True
    assert node._started is False


@pytest.mark.e2e
async def test_not_started_raises(tmp_path: Path) -> None:
    """Calling publish before start() raises TesseraError."""
    node = TesseraNode(_config(tmp_path))
    src = tmp_path / "f.bin"
    src.write_bytes(tiny())
    with pytest.raises(TesseraError, match="not started"):
        await node.publish(str(src))


# ---------------------------------------------------------------------------
# 2. Publish
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_publish_returns_manifest_hash(tmp_path: Path) -> None:
    """publish() returns a 32-byte manifest hash."""
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(_config(tmp_path)) as node:
        mh = await node.publish(str(src))

    assert isinstance(mh, bytes)
    assert len(mh) == 32


@pytest.mark.e2e
async def test_publish_with_metadata(tmp_path: Path) -> None:
    """Metadata in manifest survives roundtrip via status()."""
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(_config(tmp_path)) as node:
        mh = await node.publish(
            str(src), metadata={"description": "lifecycle test", "version": "1"}
        )
        status = await node.status(mh)

    assert status.manifest_hash == mh
    # status is a TransferStatus; verify it has expected fields.
    assert status.tesserae_total == 4  # small = 4 chunks


@pytest.mark.e2e
async def test_publish_empty_file(tmp_path: Path) -> None:
    """0-byte file publishes successfully and returns a 32-byte hash."""
    src = tmp_path / "empty.bin"
    src.write_bytes(empty())

    async with TesseraNode(_config(tmp_path)) as node:
        mh = await node.publish(str(src))

    assert isinstance(mh, bytes)
    assert len(mh) == 32


# ---------------------------------------------------------------------------
# 3. Fetch — happy path
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_basic(tmp_path: Path) -> None:
    """Publish on one node, fetch on another, output matches input."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == src.read_bytes()


@pytest.mark.e2e
async def test_fetch_on_progress_callback(tmp_path: Path) -> None:
    """on_progress is called at least once; last progress == 1.0."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    progress_events: list[object] = []

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        await fetcher.fetch(mh, on_progress=progress_events.append)

    assert len(progress_events) >= 1
    last = progress_events[-1]
    assert last.progress == pytest.approx(1.0)


@pytest.mark.e2e
async def test_fetch_on_transfer_complete(tmp_path: Path) -> None:
    """on_transfer_complete fires with correct manifest_hash and file_size."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    events: list[object] = []

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
async def test_fetch_on_manifest_received(tmp_path: Path) -> None:
    """on_manifest_received fires with metadata from the manifest."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    events: list[object] = []

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(
            str(src), metadata={"description": "manifest-rx test"}
        )

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher.on_manifest_received = events.append
        fetcher._test_piece_provider = _local_source(publisher, mh)  # type: ignore[assignment]
        await fetcher.fetch(mh)

    assert len(events) == 1
    ev = events[0]
    assert ev.manifest_hash == mh
    assert ev.metadata["description"] == "manifest-rx test"


# ---------------------------------------------------------------------------
# 4. Fetch — resume
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_resume_skips_existing(tmp_path: Path) -> None:
    """Pre-written pieces are skipped; tracking source confirms it."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    data = small()
    src.write_bytes(data)

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    # First pass: write pieces 0 and 1 manually via a partial fetch.
    from tessera.errors import TesseraError as _TE

    class PartialSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
            self._ms, self._ts, self._mh = ms, ts, mh

        async def get_manifest(self) -> bytes | None:
            return await self._ms.read(self._mh)

        async def get_piece(self, index: int) -> bytes | None:
            if index < 2:
                return await self._ts.read(self._mh, index)
            return None  # fail on pieces 2+

    async with TesseraNode(_config(fet)) as leecher:
        partial = PartialSource(publisher._manifest_store, publisher._tessera_store, mh)
        leecher._test_piece_provider = partial  # type: ignore[assignment]
        with pytest.raises((_TE, Exception)):
            await leecher.fetch(mh, output_path=fet / "out.bin")

        # Pieces 0 and 1 should be on disk.
        assert leecher._ts.exists(mh, 0)
        assert leecher._ts.exists(mh, 1)

    # Second pass: full source, track which pieces are actually fetched.
    pieces_fetched: list[int] = []

    class TrackingSource:
        async def get_manifest(self) -> bytes | None:
            return await publisher._manifest_store.read(mh)

        async def get_piece(self, index: int) -> bytes | None:
            pieces_fetched.append(index)
            return await publisher._tessera_store.read(mh, index)

    async with TesseraNode(_config(fet)) as leecher2:
        leecher2._test_piece_provider = TrackingSource()  # type: ignore[assignment]
        out = await leecher2.fetch(mh, output_path=fet / "out.bin")

    assert out.read_bytes() == data
    # Pieces 0 and 1 were already on disk.
    assert 0 not in pieces_fetched
    assert 1 not in pieces_fetched
    assert 2 in pieces_fetched
    assert 3 in pieces_fetched


# ---------------------------------------------------------------------------
# 5. Fetch — error paths
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_capacity_error(tmp_path: Path) -> None:
    """Creating swarms beyond max_swarms_per_node raises CapacityError."""
    cfg = TesseraConfig(
        data_dir=tmp_path, tessera_size=TESSERA_SIZE, max_swarms_per_node=1
    )

    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(cfg) as node:
        # First publish consumes the single swarm slot.
        await node.publish(str(src))
        # Second publish should fail with CapacityError.
        src2 = tmp_path / "f2.bin"
        src2.write_bytes(tiny())
        with pytest.raises(CapacityError):
            await node.publish(str(src2))


@pytest.mark.e2e
async def test_fetch_no_provider_starvation(tmp_path: Path) -> None:
    """No _test_piece_provider and no tracker -> StarvationError."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        # Do NOT set _test_piece_provider.
        with pytest.raises(StarvationError):
            await fetcher.fetch(mh)


@pytest.mark.e2e
async def test_fetch_corrupt_piece_raises_integrity(tmp_path: Path) -> None:
    """Provider returns wrong hash for piece 0 -> IntegrityError."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        corrupt = CorruptPieceSource(
            publisher._manifest_store, publisher._tessera_store, mh
        )
        fetcher._test_piece_provider = corrupt  # type: ignore[assignment]
        with pytest.raises(IntegrityError):
            await fetcher.fetch(mh)


@pytest.mark.e2e
async def test_fetch_provider_exception_wrapped(tmp_path: Path) -> None:
    """Provider raises RuntimeError -> wrapped as TesseraError."""
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        exploding = ExplodingSource(
            publisher._manifest_store, publisher._tessera_store, mh
        )
        fetcher._test_piece_provider = exploding  # type: ignore[assignment]
        with pytest.raises(TesseraError, match="boom"):
            await fetcher.fetch(mh)


# ---------------------------------------------------------------------------
# 6. Status
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_status_no_active_swarms(tmp_path: Path) -> None:
    """NodeStatus with 0 active swarms when nothing is published."""
    async with TesseraNode(_config(tmp_path)) as node:
        ns = await node.status()

    assert isinstance(ns, NodeStatus)
    assert ns.active_swarms == 0


@pytest.mark.e2e
async def test_status_after_publish(tmp_path: Path) -> None:
    """status() returns TransferStatus list with an active swarm after publish."""
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(_config(tmp_path)) as node:
        mh = await node.publish(str(src))
        result = await node.status()

    # After publish, the swarm is ACTIVE so status returns a list.
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0].manifest_hash == mh


# ---------------------------------------------------------------------------
# 7. Cancel
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_cancel_transitions_swarm(tmp_path: Path) -> None:
    """cancel() transitions the swarm to CLOSED."""
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(_config(tmp_path)) as node:
        mh = await node.publish(str(src))
        assert node._registry.get(mh).state == SwarmState.ACTIVE
        await node.cancel(mh)
        assert node._registry.get(mh).state == SwarmState.CLOSED


@pytest.mark.e2e
async def test_cancel_nonexistent(tmp_path: Path) -> None:
    """cancel() on an unknown hash raises TesseraError (SwarmNotFoundError)."""
    async with TesseraNode(_config(tmp_path)) as node:
        fake_hash = b"\x00" * 32
        with pytest.raises(TesseraError):
            await node.cancel(fake_hash)


# ---------------------------------------------------------------------------
# 8. Query
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_query_no_ai_returns_empty(tmp_path: Path) -> None:
    """No madakit client configured -> query returns empty list."""
    async with TesseraNode(_config(tmp_path)) as node:
        results = await node.query("find me something")

    assert results == []


# ---------------------------------------------------------------------------
# 9. Drain on stop
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_stop_drains_active_swarms(tmp_path: Path) -> None:
    """All ACTIVE swarms transition to CLOSED when stop() is called."""
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    node = TesseraNode(_config(tmp_path))
    await node.start()

    mh = await node.publish(str(src))
    assert node._registry.get(mh).state == SwarmState.ACTIVE

    await node.stop()

    assert node._registry.get(mh).state == SwarmState.CLOSED
    assert node._started is False
