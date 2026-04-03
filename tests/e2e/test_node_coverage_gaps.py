"""E2E tests: close remaining coverage gaps in tessera/node.py.

These tests target specific uncovered lines/branches identified by
coverage analysis. Each test is annotated with the line(s) it covers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import CapacityError, TesseraError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tessera.types import SwarmState
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(path: Path, **overrides: object) -> TesseraConfig:
    return TesseraConfig(data_dir=path, tessera_size=TESSERA_SIZE, **overrides)


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


class NoneManifestSource:
    """Piece source that returns None for the manifest."""

    async def get_manifest(self) -> bytes | None:
        return None

    async def get_piece(self, index: int) -> bytes | None:
        return None


def _local_source(seeder: TesseraNode, mh: bytes) -> LocalPeerSource:
    assert seeder._manifest_store is not None
    assert seeder._tessera_store is not None
    return LocalPeerSource(seeder._manifest_store, seeder._tessera_store, mh)


# ---------------------------------------------------------------------------
# Lines 147-150: TrackerBackend setup (conditional import)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_node_with_tracker_urls(tmp_path: Path) -> None:
    """When tracker_urls are configured, _discovery is set up during start().

    Covers node.py lines 147-150.
    """
    cfg = TesseraConfig(
        data_dir=tmp_path,
        tessera_size=TESSERA_SIZE,
        tracker_urls=["http://localhost:9999"],
    )
    async with TesseraNode(cfg) as node:
        assert node._discovery is not None


# ---------------------------------------------------------------------------
# Lines 161-162: Exception in stop() during swarm transition (pass)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_stop_ignores_transition_errors(tmp_path: Path) -> None:
    """stop() does not crash when a swarm transition fails.

    Covers node.py lines 161-162 (except Exception: pass).
    Publish creates an ACTIVE swarm. Monkey-patch registry.transition
    to raise an exception so the except block is entered.
    """
    cfg = _config(tmp_path)
    node = TesseraNode(cfg)
    await node.start()

    src = tmp_path / "f.bin"
    src.write_bytes(small())
    mh = await node.publish(str(src))
    assert node._registry.get(mh).state == SwarmState.ACTIVE

    # Monkey-patch transition to always raise.
    original_transition = node._registry.transition

    def _exploding_transition(manifest_hash: bytes, new_state: SwarmState) -> object:
        raise RuntimeError("transition deliberately broken")

    node._registry.transition = _exploding_transition  # type: ignore[assignment]

    # stop() should not crash despite the broken transition.
    await node.stop()
    assert not node._started

    # Restore so cleanup does not break.
    node._registry.transition = original_transition  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Line 206: FileNotFoundError for non-existent file in publish
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_publish_nonexistent_file_raises(tmp_path: Path) -> None:
    """publish() raises FileNotFoundError for a missing file.

    Covers node.py line 206.
    """
    cfg = _config(tmp_path)
    async with TesseraNode(cfg) as node:
        with pytest.raises(FileNotFoundError, match="file not found"):
            await node.publish(str(tmp_path / "nonexistent.bin"))


# ---------------------------------------------------------------------------
# Lines 243->248, 249: Swarm already exists check in publish
# (has() returns True, skip create; discovery announce)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_publish_same_file_twice_skips_swarm_create(tmp_path: Path) -> None:
    """Publishing the same file twice hits the 'swarm already exists' guard.

    Covers node.py lines 243->248 (if not has: skip) and 249
    (discovery announce when self._discovery is not None).
    """
    cfg = TesseraConfig(
        data_dir=tmp_path,
        tessera_size=TESSERA_SIZE,
        tracker_urls=["http://localhost:9999"],
    )
    src = tmp_path / "data.bin"
    src.write_bytes(tiny())

    fixed_meta = {"name": "data.bin", "created_at": "2026-01-01T00:00:00+00:00"}
    async with TesseraNode(cfg) as node:
        mh1 = await node.publish(str(src), metadata=fixed_meta)
        # Second publish of the same file produces the same manifest hash
        # and hits the `if not self._registry.has(manifest_hash)` guard.
        mh2 = await node.publish(str(src), metadata=fixed_meta)
        assert mh1 == mh2
        # Swarm should still be ACTIVE (not re-created).
        assert node._registry.get(mh1).state == SwarmState.ACTIVE


# ---------------------------------------------------------------------------
# Line 290: CapacityError branch in fetch
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_capacity_error(tmp_path: Path) -> None:
    """fetch() raises CapacityError when max_swarms_per_node is reached.

    Covers node.py line 290.
    """
    cfg = TesseraConfig(
        data_dir=tmp_path,
        tessera_size=TESSERA_SIZE,
        max_swarms_per_node=1,
    )
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(cfg) as node:
        # Consume the single swarm slot with a publish.
        await node.publish(str(src))
        # fetch() with a different hash should fail with CapacityError.
        with pytest.raises(CapacityError):
            await node.fetch(b"\xaa" * 32)


# ---------------------------------------------------------------------------
# Lines 295->299: Swarm already exists check in fetch
# (registry.has() returns True, skip create)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_existing_swarm_reuses_entry(tmp_path: Path) -> None:
    """fetch() on a manifest that already has a swarm entry reuses it.

    Covers node.py lines 295->299 (skip create when has() is True).
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        # Manually create a swarm entry so that has() returns True.
        fetcher._registry.create(mh, role="leecher")
        assert fetcher._registry.has(mh)

        fetcher._test_piece_provider = _local_source(publisher, mh)
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == src.read_bytes()


# ---------------------------------------------------------------------------
# Line 309: TesseraError when manifest source returns None
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_null_manifest_raises(tmp_path: Path) -> None:
    """fetch() raises TesseraError when the piece source returns None manifest.

    Covers node.py line 309.
    """
    cfg = _config(tmp_path)
    async with TesseraNode(cfg) as node:
        node._test_piece_provider = NoneManifestSource()
        with pytest.raises(TesseraError, match="could not serve manifest"):
            await node.fetch(b"\xbb" * 32)


# ---------------------------------------------------------------------------
# Line 342: TesseraError re-raise in piece provider
# (Provider raises a TesseraError directly — not wrapped)
# ---------------------------------------------------------------------------


class TesseraErrorSource(LocalPeerSource):
    """Raise a TesseraError on piece 0."""

    async def get_piece(self, index: int) -> bytes | None:
        if index == 0:
            raise TesseraError("tessera-level failure")
        return await self._ts.read(self._mh, index)


@pytest.mark.e2e
async def test_fetch_tessera_error_reraised(tmp_path: Path) -> None:
    """Provider raising TesseraError is re-raised directly (not wrapped).

    Covers node.py line 342.
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        src_obj = TesseraErrorSource(
            publisher._manifest_store, publisher._tessera_store, mh
        )
        fetcher._test_piece_provider = src_obj
        with pytest.raises(TesseraError, match="tessera-level failure"):
            await fetcher.fetch(mh)


# ---------------------------------------------------------------------------
# Lines 378->380: Status query during fetch completion
# (entry.state == PENDING -> transition to ACTIVE before DRAINING)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_fetch_pending_to_active_transition(tmp_path: Path) -> None:
    """fetch() transitions PENDING -> ACTIVE when closing the swarm.

    Covers node.py lines 378->380 (if entry.state == PENDING: True branch).
    The fetch creates the swarm in PENDING; after transfer it must
    transition through ACTIVE -> DRAINING -> CLOSED.
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = _local_source(publisher, mh)

        # Confirm swarm does not exist before fetch.
        assert not fetcher._registry.has(mh)

        out = await fetcher.fetch(mh)

        # After fetch, swarm should be CLOSED (went through PENDING->ACTIVE->DRAINING->CLOSED).
        entry = fetcher._registry.get(mh)
        assert entry.state == SwarmState.CLOSED

    assert out.read_bytes() == src.read_bytes()


@pytest.mark.e2e
async def test_fetch_already_active_skips_pending_transition(tmp_path: Path) -> None:
    """fetch() skips PENDING->ACTIVE transition if swarm is already ACTIVE.

    Covers node.py lines 378->380 (if entry.state == PENDING: False branch).
    Pre-create the swarm and transition it to ACTIVE so the check is False.
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(tiny())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    async with TesseraNode(_config(fet)) as fetcher:
        # Pre-create the swarm and advance it to ACTIVE.
        fetcher._registry.create(mh, role="leecher")
        fetcher._registry.transition(mh, SwarmState.ACTIVE)
        assert fetcher._registry.get(mh).state == SwarmState.ACTIVE

        fetcher._test_piece_provider = _local_source(publisher, mh)
        out = await fetcher.fetch(mh)

        # After fetch, swarm should be CLOSED (went through ACTIVE->DRAINING->CLOSED).
        entry = fetcher._registry.get(mh)
        assert entry.state == SwarmState.CLOSED

    assert out.read_bytes() == src.read_bytes()


# ---------------------------------------------------------------------------
# Line 415: Status for specific manifest that doesn't exist in store
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_status_unknown_manifest_raises(tmp_path: Path) -> None:
    """status(manifest_hash) raises KeyError for unknown manifest.

    Covers node.py line 415.
    """
    cfg = _config(tmp_path)
    fake_hash = b"\xff" * 32
    async with TesseraNode(cfg) as node:
        # Create a swarm entry so get() doesn't raise SwarmNotFoundError.
        node._registry.create(fake_hash, role="leecher")
        # But manifest store has nothing for this hash -> KeyError.
        with pytest.raises(KeyError, match="no manifest for"):
            await node.status(fake_hash)


# ---------------------------------------------------------------------------
# Line 448: Continue on missing manifest during status enumeration
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_status_skips_missing_manifest(tmp_path: Path) -> None:
    """status() (no arg) skips swarms whose manifest is missing from store.

    Covers node.py line 448 (continue).
    """
    cfg = _config(tmp_path)
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(cfg) as node:
        # Publish a real file so there's a real active swarm.
        mh_real = await node.publish(str(src))

        # Create a swarm for a manifest hash that doesn't exist in the store.
        fake_hash = b"\xee" * 32
        node._registry.create(fake_hash, role="leecher")
        node._registry.transition(fake_hash, SwarmState.ACTIVE)

        result = await node.status()

    # Should be a list with only the real swarm (fake one was skipped).
    assert isinstance(result, list)
    hashes = [s.manifest_hash for s in result]
    assert mh_real in hashes
    assert fake_hash not in hashes


# ---------------------------------------------------------------------------
# Lines 462->exit, 481: Cancel with state checks
# (cancel on already-CLOSED swarm takes the else branch)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_cancel_already_closed_is_noop(tmp_path: Path) -> None:
    """cancel() on an already-CLOSED swarm is a no-op.

    Covers node.py lines 462->exit (state not in PENDING/ACTIVE).
    """
    cfg = _config(tmp_path)
    src = tmp_path / "f.bin"
    src.write_bytes(small())

    async with TesseraNode(cfg) as node:
        mh = await node.publish(str(src))
        # First cancel.
        await node.cancel(mh)
        assert node._registry.get(mh).state == SwarmState.CLOSED
        # Second cancel on the already-closed swarm should not raise.
        await node.cancel(mh)
        assert node._registry.get(mh).state == SwarmState.CLOSED


# ---------------------------------------------------------------------------
# Line 481: query() with _discovery_adapter is None (unreachable normally
# since start() always creates it, but coverage shows line 481 missed)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_query_without_discovery_adapter(tmp_path: Path) -> None:
    """query() returns [] when _discovery_adapter is None.

    Covers node.py line 481.
    """
    cfg = _config(tmp_path)
    async with TesseraNode(cfg) as node:
        # Force _discovery_adapter to None.
        node._discovery_adapter = None
        results = await node.query("anything")
        assert results == []
