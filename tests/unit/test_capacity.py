"""Unit tests for CapacityEnforcer — ts-spec-007 §7."""

from __future__ import annotations

import pytest

from tessera.swarm.capacity import CapacityEnforcer
from tessera.swarm.registry import PeerInfo, SwarmEntry
from tessera.types import SwarmState

# ---------------------------------------------------------------------------
# Inline helpers (protocol-based mocks — no unittest.mock)
# ---------------------------------------------------------------------------

_MH = b"\xaa" * 32


def _make_entry(n_peers: int) -> SwarmEntry:
    """Build a SwarmEntry with *n_peers* dummy peers."""
    peers: dict[bytes, PeerInfo] = {}
    for i in range(n_peers):
        pid = i.to_bytes(8, "big")
        peers[pid] = PeerInfo(agent_id=pid, channel_id=pid, role="leecher")
    return SwarmEntry(
        manifest_hash=_MH, state=SwarmState.ACTIVE, role="seeder", peers=peers
    )


class _FakeRegistry:
    """Minimal stand-in for SwarmRegistry — only implements active_count."""

    def __init__(self, count: int) -> None:
        self._count = count

    def active_count(self) -> int:
        return self._count


class _FakeScorer:
    """Dict-backed stand-in for PeerScorer."""

    def __init__(self, scores: dict[bytes, float]) -> None:
        self._scores = scores

    def has_peer(self, pid: bytes) -> bool:
        return pid in self._scores

    def score(self, pid: bytes) -> float:
        return self._scores[pid]


# ---------------------------------------------------------------------------
# Admission checks — can_admit_peer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_can_admit_peer_when_room() -> None:
    """ts-spec-007 §7 — swarm below max_peers admits new peer."""
    enforcer = CapacityEnforcer(max_peers_per_swarm=50)
    entry = _make_entry(49)
    assert enforcer.can_admit_peer(entry) is True


@pytest.mark.unit
def test_can_admit_peer_when_full() -> None:
    """ts-spec-007 §7 — swarm at max_peers rejects new peer."""
    enforcer = CapacityEnforcer(max_peers_per_swarm=50)
    entry = _make_entry(50)
    assert enforcer.can_admit_peer(entry) is False


# ---------------------------------------------------------------------------
# Admission checks — can_create_swarm
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_can_create_swarm_when_room() -> None:
    """ts-spec-007 §7 — node below max_swarms allows new swarm."""
    enforcer = CapacityEnforcer(max_swarms_per_node=10)
    registry = _FakeRegistry(9)
    assert enforcer.can_create_swarm(registry) is True


@pytest.mark.unit
def test_can_create_swarm_when_full() -> None:
    """ts-spec-007 §7 — node at max_swarms blocks new swarm."""
    enforcer = CapacityEnforcer(max_swarms_per_node=10)
    registry = _FakeRegistry(10)
    assert enforcer.can_create_swarm(registry) is False


# ---------------------------------------------------------------------------
# Capacity remaining
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_capacity_remaining_full_swarm() -> None:
    """ts-spec-007 §7 — full swarm reports 0 remaining."""
    enforcer = CapacityEnforcer(max_peers_per_swarm=50)
    entry = _make_entry(50)
    assert enforcer.capacity_remaining(entry) == 0


@pytest.mark.unit
def test_capacity_remaining_empty_swarm() -> None:
    """ts-spec-007 §7 — empty swarm reports max remaining."""
    enforcer = CapacityEnforcer(max_peers_per_swarm=50)
    entry = _make_entry(0)
    assert enforcer.capacity_remaining(entry) == 50


# ---------------------------------------------------------------------------
# Swarms remaining
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_swarms_remaining_at_limit() -> None:
    """ts-spec-007 §7 — at node limit, 0 swarms remaining."""
    enforcer = CapacityEnforcer(max_swarms_per_node=10)
    registry = _FakeRegistry(10)
    assert enforcer.swarms_remaining(registry) == 0


@pytest.mark.unit
def test_swarms_remaining_with_room() -> None:
    """ts-spec-007 §7 — 7 active out of 10 -> 3 remaining."""
    enforcer = CapacityEnforcer(max_swarms_per_node=10)
    registry = _FakeRegistry(7)
    assert enforcer.swarms_remaining(registry) == 3


# ---------------------------------------------------------------------------
# Displacement candidate
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_displacement_candidate_picks_lowest_scorer() -> None:
    """ts-spec-007 §7 — displacement selects the peer with the lowest score below threshold."""
    enforcer = CapacityEnforcer(eviction_threshold=0.2)

    pid_a = (0).to_bytes(8, "big")
    pid_b = (1).to_bytes(8, "big")
    pid_c = (2).to_bytes(8, "big")

    peers = {
        pid_a: PeerInfo(agent_id=pid_a, channel_id=pid_a, role="leecher"),
        pid_b: PeerInfo(agent_id=pid_b, channel_id=pid_b, role="leecher"),
        pid_c: PeerInfo(agent_id=pid_c, channel_id=pid_c, role="leecher"),
    }
    entry = SwarmEntry(
        manifest_hash=_MH, state=SwarmState.ACTIVE, role="seeder", peers=peers
    )
    scorer = _FakeScorer({pid_a: 0.1, pid_b: 0.15, pid_c: 0.3})

    result = enforcer.displacement_candidate(entry, scorer)
    assert result == pid_a


@pytest.mark.unit
def test_displacement_candidate_none_when_all_above_threshold() -> None:
    """ts-spec-007 §7 — no candidate when every peer scores above threshold."""
    enforcer = CapacityEnforcer(eviction_threshold=0.2)

    pid_a = (0).to_bytes(8, "big")
    pid_b = (1).to_bytes(8, "big")

    peers = {
        pid_a: PeerInfo(agent_id=pid_a, channel_id=pid_a, role="leecher"),
        pid_b: PeerInfo(agent_id=pid_b, channel_id=pid_b, role="leecher"),
    }
    entry = SwarmEntry(
        manifest_hash=_MH, state=SwarmState.ACTIVE, role="seeder", peers=peers
    )
    scorer = _FakeScorer({pid_a: 0.5, pid_b: 0.8})

    assert enforcer.displacement_candidate(entry, scorer) is None


@pytest.mark.unit
def test_displacement_candidate_none_when_empty() -> None:
    """ts-spec-007 §7 — no candidate when swarm has zero peers."""
    enforcer = CapacityEnforcer(eviction_threshold=0.2)
    entry = _make_entry(0)
    scorer = _FakeScorer({})

    assert enforcer.displacement_candidate(entry, scorer) is None
