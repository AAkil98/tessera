"""Integration tests for PeerConnector — admission sequence and eviction logic.

Tests cover the 7-step admission flow, capacity enforcement, blocklist
handling, channel failure tolerance, eviction (with optional blocklist),
scorer integration, and displacement candidate selection.
"""

from __future__ import annotations

import pytest

from tessera.swarm.connector import PeerConnector
from tessera.swarm.registry import SwarmRegistry
from tessera.transfer.scorer import PeerScorer
from tessera.wire import errors as werr

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MH = b"\xaa" * 32
_PEER_A = b"\x01" * 32
_PEER_B = b"\x02" * 32
_PEER_C = b"\x03" * 32
_PEER_D = b"\x04" * 32
_BF = b"\xff"
_TC = 8


# ---------------------------------------------------------------------------
# Mock MFP handles
# ---------------------------------------------------------------------------


class _MockMFP:
    """Minimal MFP handle that records channel operations in memory."""

    def __init__(self) -> None:
        self.channels: dict[bytes, bytes] = {}
        self._next_id = 0
        self.sends: list[tuple[bytes, bytes]] = []
        self.closed: list[bytes] = []

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        self._next_id += 1
        cid = self._next_id.to_bytes(8, "big")
        self.channels[cid] = peer_agent_id
        return cid

    async def send(self, channel_id: bytes, payload: bytes) -> None:
        self.sends.append((channel_id, payload))

    async def close_channel(self, channel_id: bytes) -> None:
        self.closed.append(channel_id)


class _FailingMFP(_MockMFP):
    """MFP handle whose ``establish_channel`` always raises."""

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        raise ConnectionError("simulated failure")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(
    mfp: _MockMFP | None = None,
    registry: SwarmRegistry | None = None,
    scorer: PeerScorer | None = None,
    max_peers: int = 3,
    eviction_threshold: float = 0.2,
) -> tuple[_MockMFP, SwarmRegistry, PeerScorer, PeerConnector]:
    mfp = mfp or _MockMFP()
    registry = registry or SwarmRegistry()
    scorer = scorer or PeerScorer()
    registry.create(_MH, role="leecher")
    connector = PeerConnector(
        mfp,
        registry,
        scorer,
        max_peers_per_swarm=max_peers,
        eviction_threshold=eviction_threshold,
    )
    return mfp, registry, scorer, connector


# ---------------------------------------------------------------------------
# Admission tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_admit_success() -> None:
    """Full admission returns success=True and registers the peer."""
    mfp, registry, scorer, connector = _make_connector()

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)

    assert result.success is True
    assert result.peer_info is not None
    assert result.peer_info.agent_id == _PEER_A
    # Peer appears in the registry.
    entry = registry.get(_MH)
    assert _PEER_A in entry.peers
    # Peer appears in the scorer.
    assert scorer.has_peer(_PEER_A)


@pytest.mark.integration
async def test_admit_swarm_full() -> None:
    """When the swarm is at capacity the next admit is rejected."""
    mfp, registry, scorer, connector = _make_connector(max_peers=3)

    # Fill the swarm to capacity.
    for peer in (_PEER_A, _PEER_B, _PEER_C):
        r = await connector.admit(_MH, peer, _BF, _TC)
        assert r.success is True

    # Fourth admit must be rejected.
    result = await connector.admit(_MH, _PEER_D, _BF, _TC)
    assert result.success is False
    assert result.reject_code == werr.SWARM_FULL


@pytest.mark.integration
async def test_admit_blocklisted_peer() -> None:
    """A blocklisted peer is rejected immediately."""
    _mfp, registry, _scorer, connector = _make_connector()

    registry.blocklist_peer(_MH, _PEER_A)

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is False
    assert result.reject_code == werr.SWARM_FULL
    assert "blocklist" in result.reason


@pytest.mark.integration
async def test_admit_channel_failure() -> None:
    """When MFP fails to establish a channel, admit returns failure."""
    failing_mfp = _FailingMFP()
    _mfp, registry, scorer, connector = _make_connector(mfp=failing_mfp)

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is False
    assert "channel" in result.reason.lower()


@pytest.mark.integration
async def test_admit_sends_handshake_and_bitfield() -> None:
    """Admission sends exactly two payloads: HANDSHAKE then BITFIELD."""
    mfp, _registry, _scorer, connector = _make_connector()

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is True

    # Two sends on the same channel.
    assert len(mfp.sends) == 2
    ch1, _ = mfp.sends[0]
    ch2, _ = mfp.sends[1]
    assert ch1 == ch2  # same channel for both messages


@pytest.mark.integration
async def test_admit_registers_in_scorer() -> None:
    """After admission the peer is tracked by the scorer."""
    _mfp, _registry, scorer, connector = _make_connector()

    assert not scorer.has_peer(_PEER_A)
    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.success is True
    assert scorer.has_peer(_PEER_A)


@pytest.mark.integration
async def test_admit_low_trust() -> None:
    """Low-trust admission assigns a lower initial score."""
    _mfp, _registry, scorer, connector = _make_connector()

    # Admit two peers: one normal, one low-trust.
    await connector.admit(_MH, _PEER_A, _BF, _TC, low_trust=False)
    await connector.admit(_MH, _PEER_B, _BF, _TC, low_trust=True)

    score_normal = scorer.score(_PEER_A)
    score_low = scorer.score(_PEER_B)
    assert score_low < score_normal


# ---------------------------------------------------------------------------
# Eviction tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_evict_removes_from_registry() -> None:
    """After eviction the peer no longer appears in the swarm's peer list."""
    _mfp, registry, _scorer, connector = _make_connector()

    await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert _PEER_A in registry.get(_MH).peers

    await connector.evict(_MH, _PEER_A, reason="test")
    assert _PEER_A not in registry.get(_MH).peers


@pytest.mark.integration
async def test_evict_closes_channel() -> None:
    """Eviction closes the MFP channel for the peer."""
    mfp, _registry, _scorer, connector = _make_connector()

    result = await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert result.peer_info is not None
    channel_id = result.peer_info.channel_id

    await connector.evict(_MH, _PEER_A, reason="test")
    assert channel_id in mfp.closed


@pytest.mark.integration
async def test_evict_with_blocklist() -> None:
    """Eviction with blocklist=True adds the peer to the blocklist."""
    _mfp, registry, _scorer, connector = _make_connector()

    await connector.admit(_MH, _PEER_A, _BF, _TC)
    await connector.evict(_MH, _PEER_A, reason="misbehaving", blocklist=True)

    assert registry.is_blocklisted(_MH, _PEER_A)


@pytest.mark.integration
async def test_evict_removes_from_scorer() -> None:
    """After eviction the scorer no longer tracks the peer."""
    _mfp, _registry, scorer, connector = _make_connector()

    await connector.admit(_MH, _PEER_A, _BF, _TC)
    assert scorer.has_peer(_PEER_A)

    await connector.evict(_MH, _PEER_A, reason="test")
    assert not scorer.has_peer(_PEER_A)


# ---------------------------------------------------------------------------
# Score-based eviction and displacement
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_should_evict_for_score_true() -> None:
    """A peer whose score drops below the hard floor is flagged for eviction."""
    _mfp, _registry, scorer, connector = _make_connector()

    await connector.admit(_MH, _PEER_A, _BF, _TC)

    # Drive the score below the MIN_PEER_SCORE (0.1) hard floor.
    for _ in range(10):
        scorer.on_hash_mismatch(_PEER_A)

    assert connector.should_evict_for_score(_PEER_A) is True


@pytest.mark.integration
async def test_candidate_for_displacement() -> None:
    """The lowest-scoring peer below the eviction threshold is returned."""
    _mfp, _registry, scorer, connector = _make_connector(
        max_peers=3,
        eviction_threshold=0.2,
    )

    await connector.admit(_MH, _PEER_A, _BF, _TC)
    await connector.admit(_MH, _PEER_B, _BF, _TC)

    # Degrade PEER_A below the threshold; leave PEER_B untouched.
    for _ in range(6):
        scorer.on_hash_mismatch(_PEER_A)

    candidate = connector.candidate_for_displacement(_MH)
    assert candidate == _PEER_A


@pytest.mark.integration
async def test_candidate_for_displacement_none() -> None:
    """When all peers are above the threshold no candidate is returned."""
    _mfp, _registry, _scorer, connector = _make_connector(
        max_peers=3,
        eviction_threshold=0.2,
    )

    await connector.admit(_MH, _PEER_A, _BF, _TC)
    await connector.admit(_MH, _PEER_B, _BF, _TC)

    # Both peers keep their healthy default scores.
    assert connector.candidate_for_displacement(_MH) is None
