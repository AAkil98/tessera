"""Adversarial tests: bandwidth/resource exhaustion -- ts-spec-013 section 6.9, T10.

Resource exhaustion scenarios exercising capacity limits at the unit level.
These use CapacityEnforcer, RequestPipeline, and SwarmRegistry directly
(no TesseraNode required).

  - Creating max+1 swarms: CapacityEnforcer rejects the attempt.
  - Admitting max+1 peers: CapacityEnforcer rejects the admission.
  - Pipeline max retries exhausted: MaxRetriesExceeded is raised.
"""

from __future__ import annotations

import pytest

from tessera.swarm.capacity import CapacityEnforcer
from tessera.swarm.registry import PeerInfo, SwarmEntry, SwarmRegistry
from tessera.transfer.pipeline import MaxRetriesExceeded, RequestPipeline
from tessera.types import SwarmState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peer_id(n: int) -> bytes:
    """Generate a deterministic 8-byte peer id."""
    return n.to_bytes(8, "big")


def _make_entry(n_peers: int) -> SwarmEntry:
    """Build a SwarmEntry pre-loaded with n_peers dummy peers."""
    mh = b"\xcc" * 32
    peers: dict[bytes, PeerInfo] = {}
    for i in range(n_peers):
        pid = _peer_id(i)
        peers[pid] = PeerInfo(agent_id=pid, channel_id=pid, role="leecher")
    return SwarmEntry(
        manifest_hash=mh,
        state=SwarmState.ACTIVE,
        role="seeder",
        peers=peers,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
async def test_many_swarms_capacity_enforced() -> None:
    """Creating max+1 swarms is rejected by CapacityEnforcer.

    ts-spec-007 section 7: max_swarms_per_node limits how many concurrent
    swarms a single node may manage. When the limit is reached,
    can_create_swarm returns False.
    """
    max_swarms = 3
    enforcer = CapacityEnforcer(max_swarms_per_node=max_swarms)
    registry = SwarmRegistry()

    # Fill up to the limit.
    for i in range(max_swarms):
        mh = (i + 1).to_bytes(32, "big")
        registry.create(mh, role="seeder")

    assert registry.active_count() == max_swarms
    assert enforcer.can_create_swarm(registry) is False
    assert enforcer.swarms_remaining(registry) == 0


@pytest.mark.adversarial
async def test_many_peers_capacity_enforced() -> None:
    """Admitting max+1 peers to a swarm is rejected by CapacityEnforcer.

    ts-spec-007 section 7: max_peers_per_swarm limits peer count. When the
    swarm is full, can_admit_peer returns False.
    """
    max_peers = 5
    enforcer = CapacityEnforcer(max_peers_per_swarm=max_peers)
    entry = _make_entry(max_peers)

    assert len(entry.peers) == max_peers
    assert enforcer.can_admit_peer(entry) is False
    assert enforcer.capacity_remaining(entry) == 0

    # Removing one peer should open a slot.
    first_pid = _peer_id(0)
    del entry.peers[first_pid]
    assert enforcer.can_admit_peer(entry) is True
    assert enforcer.capacity_remaining(entry) == 1


@pytest.mark.adversarial
async def test_pipeline_max_retries_exhausted() -> None:
    """Pipeline raises MaxRetriesExceeded after the configured retry limit.

    ts-spec-008 section 5: each tessera index has a per-index retry counter.
    When max_retries attempts have been made, the pipeline refuses further
    attempts and raises MaxRetriesExceeded.
    """
    max_retries = 3
    pipe = RequestPipeline(max_retries=max_retries)
    peer = _peer_id(1)
    target_index = 7

    # Exhaust all retries by acquiring and releasing.
    for _ in range(max_retries):
        record = await pipe.acquire(peer, target_index)
        pipe.release(record)

    assert pipe.retry_count(target_index) == max_retries

    # The next attempt must raise MaxRetriesExceeded.
    with pytest.raises(MaxRetriesExceeded) as exc_info:
        await pipe.acquire(peer, target_index)

    assert exc_info.value.index == target_index
    assert exc_info.value.attempts == max_retries

    # The index should now appear in stuck_tesserae.
    assert target_index in pipe.stuck_tesserae()
