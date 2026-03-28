"""Unit tests for SwarmRegistry and SwarmEntry — ts-spec-007 §2."""

from __future__ import annotations

import pytest

from tessera.swarm.registry import (
    PeerInfo,
    SwarmNotFoundError,
    SwarmRegistry,
)
from tessera.types import SwarmState

_MH = b"\xaa" * 32
_MH2 = b"\xbb" * 32
_PEER_A = b"\x01" * 8
_PEER_B = b"\x02" * 8
_PEER_C = b"\x03" * 8


# ---------------------------------------------------------------------------
# Swarm lifecycle — create
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_returns_pending_entry() -> None:
    """ts-spec-007 §2 — new swarm starts in PENDING state."""
    reg = SwarmRegistry()
    entry = reg.create(_MH, "seeder")
    assert entry.manifest_hash == _MH
    assert entry.state == SwarmState.PENDING
    assert entry.role == "seeder"
    assert entry.peers == {}


@pytest.mark.unit
def test_create_duplicate_raises_value_error() -> None:
    """ts-spec-007 §2 — duplicate manifest_hash is rejected."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    with pytest.raises(ValueError):
        reg.create(_MH, "leecher")


# ---------------------------------------------------------------------------
# Swarm lifecycle — get
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_returns_entry() -> None:
    """ts-spec-007 §2 — get returns the created entry."""
    reg = SwarmRegistry()
    created = reg.create(_MH, "seeder")
    assert reg.get(_MH) is created


@pytest.mark.unit
def test_get_nonexistent_raises_swarm_not_found() -> None:
    """ts-spec-007 §2 — unknown hash raises SwarmNotFoundError."""
    reg = SwarmRegistry()
    with pytest.raises(SwarmNotFoundError):
        reg.get(_MH)


# ---------------------------------------------------------------------------
# Swarm lifecycle — transition
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_transition_pending_to_active() -> None:
    """ts-spec-007 §2 — PENDING -> ACTIVE is allowed."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    entry = reg.transition(_MH, SwarmState.ACTIVE)
    assert entry.state == SwarmState.ACTIVE


@pytest.mark.unit
def test_transition_pending_to_draining() -> None:
    """ts-spec-007 §2 — PENDING -> DRAINING is allowed (e.g. cancel before any peer)."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    entry = reg.transition(_MH, SwarmState.DRAINING)
    assert entry.state == SwarmState.DRAINING


@pytest.mark.unit
def test_transition_active_to_draining() -> None:
    """ts-spec-007 §2 — ACTIVE -> DRAINING is allowed."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    entry = reg.transition(_MH, SwarmState.DRAINING)
    assert entry.state == SwarmState.DRAINING


@pytest.mark.unit
def test_transition_draining_to_closed() -> None:
    """ts-spec-007 §2 — DRAINING -> CLOSED is allowed and sets completed_at."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    reg.transition(_MH, SwarmState.DRAINING)
    entry = reg.transition(_MH, SwarmState.CLOSED)
    assert entry.state == SwarmState.CLOSED
    assert entry.completed_at is not None


@pytest.mark.unit
def test_transition_closed_is_terminal() -> None:
    """ts-spec-007 §2 — CLOSED is a terminal state; any transition raises."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    reg.transition(_MH, SwarmState.DRAINING)
    reg.transition(_MH, SwarmState.CLOSED)
    with pytest.raises(ValueError):
        reg.transition(_MH, SwarmState.ACTIVE)


@pytest.mark.unit
def test_transition_backwards_rejected() -> None:
    """ts-spec-007 §2 — ACTIVE -> PENDING is not a valid transition."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    with pytest.raises(ValueError):
        reg.transition(_MH, SwarmState.PENDING)


# ---------------------------------------------------------------------------
# Swarm lifecycle — remove
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_remove_closed_swarm() -> None:
    """ts-spec-007 §2 — CLOSED swarm can be removed from the registry."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    reg.transition(_MH, SwarmState.DRAINING)
    reg.transition(_MH, SwarmState.CLOSED)
    reg.remove(_MH)
    assert reg.has(_MH) is False


@pytest.mark.unit
def test_remove_non_closed_raises() -> None:
    """ts-spec-007 §2 — removing a non-CLOSED swarm raises ValueError."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    with pytest.raises(ValueError):
        reg.remove(_MH)


# ---------------------------------------------------------------------------
# Peer management
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_add_peer_transitions_pending_to_active() -> None:
    """ts-spec-007 §2 — first add_peer auto-transitions PENDING -> ACTIVE."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    peer = PeerInfo(agent_id=_PEER_A, channel_id=_PEER_A, role="leecher")
    reg.add_peer(_MH, peer)
    assert reg.get(_MH).state == SwarmState.ACTIVE
    assert _PEER_A in reg.get(_MH).peers


@pytest.mark.unit
def test_add_peer_to_nonexistent_raises() -> None:
    """ts-spec-007 §2 — add_peer on unknown swarm raises SwarmNotFoundError."""
    reg = SwarmRegistry()
    peer = PeerInfo(agent_id=_PEER_A, channel_id=_PEER_A, role="leecher")
    with pytest.raises(SwarmNotFoundError):
        reg.add_peer(_MH, peer)


@pytest.mark.unit
def test_remove_peer_returns_info() -> None:
    """ts-spec-007 §2 — removing an existing peer returns its PeerInfo."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    peer = PeerInfo(agent_id=_PEER_A, channel_id=_PEER_A, role="leecher")
    reg.add_peer(_MH, peer)
    removed = reg.remove_peer(_MH, _PEER_A)
    assert removed is not None
    assert removed.agent_id == _PEER_A


@pytest.mark.unit
def test_remove_peer_unknown_returns_none() -> None:
    """ts-spec-007 §2 — removing a peer not in the swarm returns None."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    assert reg.remove_peer(_MH, _PEER_A) is None


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_blocklist_peer() -> None:
    """ts-spec-007 §2 — blocklisted peer appears in blocklist set."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.blocklist_peer(_MH, _PEER_A)
    assert _PEER_A in reg.get(_MH).blocklist


@pytest.mark.unit
def test_is_blocklisted_true() -> None:
    """ts-spec-007 §2 — is_blocklisted returns True for blocked peer."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.blocklist_peer(_MH, _PEER_A)
    assert reg.is_blocklisted(_MH, _PEER_A) is True


@pytest.mark.unit
def test_is_blocklisted_false_unknown() -> None:
    """ts-spec-007 §2 — is_blocklisted returns False for unknown peer."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    assert reg.is_blocklisted(_MH, _PEER_B) is False


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_active_count_includes_pending_and_active() -> None:
    """ts-spec-007 §2 — PENDING and ACTIVE swarms count towards capacity."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")  # PENDING
    reg.create(_MH2, "leecher")  # PENDING
    reg.transition(_MH2, SwarmState.ACTIVE)  # now ACTIVE
    assert reg.active_count() == 2


@pytest.mark.unit
def test_active_count_excludes_draining_and_closed() -> None:
    """ts-spec-007 §2 — DRAINING and CLOSED swarms do not count."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.transition(_MH, SwarmState.ACTIVE)
    reg.transition(_MH, SwarmState.DRAINING)

    reg.create(_MH2, "leecher")
    reg.transition(_MH2, SwarmState.ACTIVE)
    reg.transition(_MH2, SwarmState.DRAINING)
    reg.transition(_MH2, SwarmState.CLOSED)

    assert reg.active_count() == 0


@pytest.mark.unit
def test_all_swarms_returns_all() -> None:
    """ts-spec-007 §2 — all_swarms returns every tracked swarm regardless of state."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    reg.create(_MH2, "leecher")
    entries = reg.all_swarms()
    hashes = {e.manifest_hash for e in entries}
    assert hashes == {_MH, _MH2}


@pytest.mark.unit
def test_has_true_and_false() -> None:
    """ts-spec-007 §2 — has() returns True for tracked, False for unknown."""
    reg = SwarmRegistry()
    reg.create(_MH, "seeder")
    assert reg.has(_MH) is True
    assert reg.has(_MH2) is False
