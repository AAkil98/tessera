"""Integration tests closing remaining coverage gaps in storage and swarm layers.

Targets uncovered lines/branches in:
  - storage/layout.py (lines 126, branches 101->107, 107->123, 123->exit)
  - storage/manifest_store.py (lines 42, 45, 58-59, 117-119)
  - storage/state.py (lines 168-170)
  - storage/tessera_store.py (lines 64-66, 115, 119->116, 121-122, 193->exit)
  - swarm/connector.py (lines 142-143, 194-196, 208-210, 233-236, 256->267, 271->exit, 277)
  - swarm/partition.py (branch 103->exit, line 115)
  - swarm/registry.py (line 144)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tessera.errors import MessageError
from tessera.storage.layout import (
    ensure_data_dir,
    startup_cleanup,
    tessera_dir,
)
from tessera.storage.manifest_store import ManifestIndex, ManifestStore
from tessera.storage.state import TransferState
from tessera.storage.tessera_store import TesseraStore
from tessera.swarm.connector import PeerConnector
from tessera.swarm.partition import PartitionDetector, StarvationTracker
from tessera.swarm.registry import SwarmRegistry
from tessera.transfer.scorer import PeerScorer
from tessera.wire.messages import Request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MH = b"\xaa" * 32
_PEER_A = b"\x01" * 32
_PEER_B = b"\x02" * 32
_BF = b"\xff"
_TC = 8


# ===================================================================
# 1. storage/layout.py — startup_cleanup coverage gaps
# ===================================================================


@pytest.mark.integration
def test_startup_cleanup_no_tmp_no_transfers_no_tesserae(tmp_path: Path) -> None:
    """Branches 101->107, 107->123, 123->exit: all three dirs missing."""
    # Only create the bare data_dir, no subdirs
    tmp_path.mkdir(exist_ok=True)
    # startup_cleanup should not crash when tmp/, transfers/, tesserae/ are absent
    startup_cleanup(tmp_path)


@pytest.mark.integration
def test_startup_cleanup_orphaned_tessera_dir_warning(tmp_path: Path) -> None:
    """Line 126 + lines 128-129: tessera dir with no matching state file."""
    ensure_data_dir(tmp_path)
    # Create an orphaned tessera directory (no matching state file)
    hash_hex = "ab" * 32
    td = tmp_path / "tesserae" / hash_hex
    td.mkdir(parents=True)
    # Confirm no .state file exists for this hash
    state_file = tmp_path / "transfers" / f"{hash_hex}.state"
    assert not state_file.exists()

    startup_cleanup(tmp_path)

    # The orphaned tessera dir should still exist (only a warning, not deleted)
    assert td.exists()


@pytest.mark.integration
def test_startup_cleanup_tesserae_non_dir_entry(tmp_path: Path) -> None:
    """Line 125-126: non-directory entry in tesserae/ is skipped via continue."""
    ensure_data_dir(tmp_path)
    # Create a regular file inside tesserae/ (not a directory)
    (tmp_path / "tesserae" / "not_a_directory.txt").write_text("garbage")

    startup_cleanup(tmp_path)  # Should not crash


@pytest.mark.integration
def test_startup_cleanup_stale_state_and_tessera(tmp_path: Path) -> None:
    """Lines 108-120: stale state file (no matching manifest) with tessera dir."""
    ensure_data_dir(tmp_path)
    hash_hex = "cd" * 32
    # Create a state file with no corresponding manifest
    state_file = tmp_path / "transfers" / f"{hash_hex}.state"
    state_file.write_text("{}")
    # Create a tessera directory for the same hash
    td = tmp_path / "tesserae" / hash_hex
    td.mkdir(parents=True)
    (td / "000000.piece").write_bytes(b"data")

    startup_cleanup(tmp_path)

    # Both should be cleaned up
    assert not state_file.exists()
    assert not td.exists()


# ===================================================================
# 2. storage/manifest_store.py — ManifestIndex.rebuild gaps
# ===================================================================


@pytest.mark.integration
def test_manifest_index_rebuild_no_manifests_dir(tmp_path: Path) -> None:
    """Line 42: rebuild when manifests/ directory doesn't exist -> early return."""
    ensure_data_dir(tmp_path)
    # Remove the manifests directory entirely
    shutil.rmtree(tmp_path / "manifests")

    idx = ManifestIndex()
    idx.rebuild(tmp_path)
    assert idx.all_metadata() == []


@pytest.mark.integration
def test_manifest_index_rebuild_skips_non_dir(tmp_path: Path) -> None:
    """Line 44-45: non-directory entry in manifests/ is skipped."""
    ensure_data_dir(tmp_path)
    # Create a regular file directly in manifests/ (not a prefix subdirectory)
    (tmp_path / "manifests" / "garbage.txt").write_text("x")

    idx = ManifestIndex()
    idx.rebuild(tmp_path)
    assert idx.all_metadata() == []


@pytest.mark.integration
def test_manifest_index_rebuild_skips_corrupt(tmp_path: Path) -> None:
    """Lines 58-59: exception during manifest parse is caught and skipped."""
    import hashlib as _hl

    ensure_data_dir(tmp_path)
    # Content whose SHA-256 matches the filename so the hash check passes,
    # but the content is not a valid manifest so ManifestParser.parse raises.
    content = b"not a real manifest but valid hash"
    real_hash = _hl.sha256(content).hexdigest()
    prefix_dir = tmp_path / "manifests" / real_hash[:2]
    prefix_dir.mkdir(parents=True, exist_ok=True)
    (prefix_dir / f"{real_hash}.manifest").write_bytes(content)

    idx = ManifestIndex()
    idx.rebuild(tmp_path)  # Should not crash, should skip corrupt file
    assert idx.all_metadata() == []


@pytest.mark.integration
def test_manifest_store_write_cleanup_on_failure(tmp_path: Path) -> None:
    """Lines 117-119: BaseException cleanup during _write_sync (tmp removed)."""
    import hashlib

    ensure_data_dir(tmp_path)
    store = ManifestStore(tmp_path)

    manifest_bytes = b"TSRA" + b"\x00" * 100
    h = hashlib.sha256(manifest_bytes).hexdigest()
    prefix_dir = tmp_path / "manifests" / h[:2]
    prefix_dir.mkdir(parents=True, exist_ok=True)
    # Make the prefix directory read-only so os.rename into it fails
    prefix_dir.chmod(0o444)
    try:
        with pytest.raises(OSError):
            # Call the sync method directly so coverage captures the except block
            store._write_sync(manifest_bytes)
        # No tmp files should be left behind
        tmp_dir = tmp_path / "tmp"
        leftover = list(tmp_dir.iterdir())
        assert leftover == []
    finally:
        prefix_dir.chmod(0o700)


# ===================================================================
# 3. storage/state.py — write_state cleanup on failure
# ===================================================================


@pytest.mark.integration
def test_write_state_cleanup_on_failure(tmp_path: Path) -> None:
    """Lines 168-170: BaseException cleanup during _write_state_sync."""
    from tessera.storage.state import _write_state_sync

    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(b"\xcc" * 32, 10)
    state.touch()

    # Make the transfers/ directory read-only so os.rename fails
    transfers_dir = tmp_path / "transfers"
    transfers_dir.chmod(0o444)
    try:
        with pytest.raises(OSError):
            # Call the sync function directly so coverage captures the except block
            _write_state_sync(tmp_path, state)
        # Verify no tmp files left behind
        tmp_dir = tmp_path / "tmp"
        assert list(tmp_dir.iterdir()) == []
    finally:
        transfers_dir.chmod(0o700)


# ===================================================================
# 4. storage/tessera_store.py — rebuild_bitfield + delete_mosaic gaps
# ===================================================================


@pytest.mark.integration
def test_tessera_store_write_cleanup_on_failure(tmp_path: Path) -> None:
    """Lines 64-66: BaseException cleanup during _write_sync."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xdd" * 32

    # Create the tessera directory and make it read-only so rename fails
    td = tessera_dir(tmp_path, mh)
    td.mkdir(parents=True, exist_ok=True)
    td.chmod(0o444)
    try:
        with pytest.raises(OSError):
            # Call the sync method directly so coverage captures the except block
            ts._write_sync(mh, 0, b"data")
        # No tmp files left behind
        tmp_dir = tmp_path / "tmp"
        assert list(tmp_dir.iterdir()) == []
    finally:
        td.chmod(0o700)


@pytest.mark.integration
async def test_tessera_store_rebuild_skips_non_piece_files(tmp_path: Path) -> None:
    """Line 115 (line 114->115 branch): non-.piece file in tessera dir skipped."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xdd" * 32

    # Write one valid piece
    await ts.write(mh, 0, b"data")

    # Add a non-.piece file
    td = tessera_dir(tmp_path, mh)
    (td / "readme.txt").write_text("not a piece")

    bf = await ts.rebuild_bitfield(mh, 4)
    assert bf.get(0) is True
    assert bf.count_set() == 1


@pytest.mark.integration
async def test_tessera_store_rebuild_skips_bad_filename(tmp_path: Path) -> None:
    """Lines 121-122: ValueError when piece filename stem is non-numeric."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xdd" * 32

    td = tessera_dir(tmp_path, mh)
    td.mkdir(parents=True, exist_ok=True)
    # Create a .piece file with a non-numeric stem
    (td / "notanumber.piece").write_bytes(b"x")

    bf = await ts.rebuild_bitfield(mh, 4)
    assert bf.count_set() == 0


@pytest.mark.integration
async def test_tessera_store_rebuild_skips_out_of_range(tmp_path: Path) -> None:
    """Branch 119->116: piece index >= tessera_count is skipped."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xdd" * 32

    # Write one valid piece at index 0
    await ts.write(mh, 0, b"data")

    # Create a piece with index 999 (out of range for tessera_count=4)
    td = tessera_dir(tmp_path, mh)
    (td / "000999.piece").write_bytes(b"x")

    bf = await ts.rebuild_bitfield(mh, 4)
    assert bf.get(0) is True
    assert bf.count_set() == 1  # only index 0, not 999


@pytest.mark.integration
async def test_tessera_store_rebuild_empty_dir(tmp_path: Path) -> None:
    """Line 114-115: tessera directory does not exist -> returns empty bitfield."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xee" * 32

    bf = await ts.rebuild_bitfield(mh, 4)
    assert bf.count_set() == 0


@pytest.mark.integration
async def test_tessera_store_delete_nonexistent_mosaic(tmp_path: Path) -> None:
    """Line 193->exit: delete_mosaic when directory doesn't exist."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    mh = b"\xee" * 32

    # Should not raise when the directory does not exist
    await ts.delete_mosaic(mh)


# ===================================================================
# 5. swarm/connector.py — coverage gaps
# ===================================================================


class _MockMFP:
    """Minimal MFP handle for connector tests."""

    def __init__(self) -> None:
        self._next_id = 0
        self.sends: list[tuple[bytes, bytes]] = []
        self.closed: list[bytes] = []

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        self._next_id += 1
        return self._next_id.to_bytes(8, "big")

    async def send(self, channel_id: bytes, payload: bytes) -> None:
        self.sends.append((channel_id, payload))

    async def close_channel(self, channel_id: bytes) -> None:
        self.closed.append(channel_id)


class _SecondSendFailMFP:
    """MFP handle that raises on the second send (BITFIELD send)."""

    def __init__(self) -> None:
        self._send_count = 0
        self.closed: list[bytes] = []

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        return b"\x01" * 8

    async def send(self, channel_id: bytes, payload: bytes) -> None:
        self._send_count += 1
        if self._send_count == 2:
            raise ConnectionError("simulated BITFIELD send failure")

    async def close_channel(self, channel_id: bytes) -> None:
        self.closed.append(channel_id)


class _FirstSendFailMFP:
    """MFP handle that raises on the first send (HANDSHAKE send)."""

    def __init__(self) -> None:
        self.closed: list[bytes] = []

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        return b"\x02" * 8

    async def send(self, channel_id: bytes, payload: bytes) -> None:
        raise ConnectionError("simulated HANDSHAKE send failure")

    async def close_channel(self, channel_id: bytes) -> None:
        self.closed.append(channel_id)


def _make_connector(
    mfp: _MockMFP | None = None,
    registry: SwarmRegistry | None = None,
    scorer: PeerScorer | None = None,
    max_peers: int = 50,
    *,
    create_swarm: bool = True,
) -> tuple[object, SwarmRegistry, PeerScorer, PeerConnector]:
    mfp = mfp or _MockMFP()
    registry = registry or SwarmRegistry()
    scorer = scorer or PeerScorer()
    if create_swarm:
        registry.create(_MH, role="leecher")
    return mfp, registry, scorer, PeerConnector(
        mfp, registry, scorer, max_peers_per_swarm=max_peers
    )


@pytest.mark.integration
async def test_admit_swarm_not_found() -> None:
    """Lines 142-143: admit when swarm is not in registry."""
    _, registry, scorer, connector = _make_connector(create_swarm=False)

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is False
    assert "swarm not found" in result.reason


@pytest.mark.integration
async def test_admit_handshake_send_failure() -> None:
    """Lines 194-196: HANDSHAKE send fails -> cleanup + failure result."""
    mfp = _FirstSendFailMFP()
    _, _, _, connector = _make_connector(mfp=mfp)

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is False
    assert "HANDSHAKE" in result.reason


@pytest.mark.integration
async def test_admit_bitfield_send_failure() -> None:
    """Lines 208-210: BITFIELD send fails -> cleanup + failure result."""
    mfp = _SecondSendFailMFP()
    _, _, _, connector = _make_connector(mfp=mfp)

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is False
    assert "BITFIELD" in result.reason
    # Channel should have been cleaned up (close_channel called)
    assert len(mfp.closed) == 1


@pytest.mark.integration
async def test_on_receive_unknown_channel() -> None:
    """Lines 233-236: on_receive with channel_id not in sessions."""
    _, _, _, connector = _make_connector()
    unknown_channel = b"\xff" * 8

    with pytest.raises(MessageError, match="no session for channel"):
        connector.on_receive(_MH, unknown_channel, Request(index=0))


@pytest.mark.integration
async def test_evict_nonexistent_peer() -> None:
    """Lines 256->267: evict peer not in registry (remove_peer returns None)."""
    _, _, _, connector = _make_connector()

    # Evict a peer that was never admitted -- should not crash
    await connector.evict(_MH, _PEER_A, reason="not present")


@pytest.mark.integration
async def test_evict_peer_not_in_scorer() -> None:
    """Branch 271->exit: evict peer that exists in registry but not in scorer."""
    mfp, registry, scorer, connector = _make_connector()

    # Admit the peer normally (adds to both registry and scorer)
    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is True

    # Manually remove from scorer before evicting
    scorer.remove_peer(_PEER_A)
    assert not scorer.has_peer(_PEER_A)

    # Evict should still work without crashing
    await connector.evict(_MH, _PEER_A, reason="test scorer skip")
    assert _PEER_A not in registry.get(_MH).peers


@pytest.mark.integration
async def test_on_receive_valid_session() -> None:
    """Line 236: on_receive dispatches to session.on_receive on valid channel."""
    from tessera.wire.messages import BitfieldMsg, Handshake

    mfp, _, _, connector = _make_connector()

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is True
    channel_id = result.peer_info.channel_id

    # The session is in AWAITING_HANDSHAKE state on the receive side.
    # Send a valid HANDSHAKE to advance it.
    hs = Handshake(
        version=0x0001,
        manifest_hash=_MH,
        tessera_count=_TC,
        tessera_size=262_144,
    )
    connector.on_receive(_MH, channel_id, hs)

    # Now send BITFIELD to advance to TRANSFER state.
    bf_msg = BitfieldMsg(bitfield_bytes=_BF)
    connector.on_receive(_MH, channel_id, bf_msg)

    # Now a transfer-phase message should work.
    connector.on_receive(_MH, channel_id, Request(index=0))


@pytest.mark.integration
async def test_should_evict_for_score_unknown_peer() -> None:
    """Line 277: should_evict_for_score returns False for unknown peer."""
    _, _, _, connector = _make_connector()

    # Peer was never admitted -- has_peer returns False
    assert connector.should_evict_for_score(_PEER_A) is False


# ===================================================================
# 6. swarm/partition.py — StarvationTracker gaps
# ===================================================================


@pytest.mark.integration
def test_starvation_should_rediscover_false_when_peers_connected() -> None:
    """Branch 103->exit (line 114-115): should_rediscover returns False
    when peers are connected (_zero_since is None)."""
    tracker = StarvationTracker()
    # Initially no starvation -- peers haven't been lost
    assert tracker.should_rediscover() is False

    # Report some peers connected
    tracker.on_peer_count(3)
    assert tracker.should_rediscover() is False


@pytest.mark.integration
def test_starvation_on_peer_count_zero_twice() -> None:
    """Branch 103->exit: on_peer_count(0) when _zero_since is already set.
    The inner 'if self._zero_since is None' is False so it falls through."""
    tracker = StarvationTracker()
    # First call with 0 sets _zero_since
    tracker.on_peer_count(0)
    assert tracker.should_rediscover() is True

    # Second call with 0 when _zero_since is already set -- hits branch 103->exit
    tracker.on_peer_count(0)
    assert tracker.should_rediscover() is True


@pytest.mark.integration
def test_partition_detector_dead_peers_empty() -> None:
    """Line 115-like (dead_peers with no peers registered)."""
    detector = PartitionDetector()
    assert detector.dead_peers() == []


# ===================================================================
# 7. swarm/registry.py — remove_peer on non-existent swarm
# ===================================================================


@pytest.mark.integration
def test_registry_remove_peer_nonexistent_swarm() -> None:
    """Line 144: remove_peer on a manifest_hash not in registry returns None."""
    registry = SwarmRegistry()
    unknown_hash = b"\xff" * 32

    result = registry.remove_peer(unknown_hash, _PEER_A)
    assert result is None
