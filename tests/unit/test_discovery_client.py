"""Unit tests for DiscoveryClient — ts-spec-007 §6."""

from __future__ import annotations

import time
from typing import Literal

import pytest

from tessera.discovery.backend import PeerRecord
from tessera.discovery.client import DiscoveryClient, RankedPeer, TrustLevel

_MH = b"\xaa" * 32
_PEER_A = b"\x01" * 32
_PEER_B = b"\x02" * 32
_PEER_C = b"\x03" * 32


# ---------------------------------------------------------------------------
# Mock backend (protocol-based, no unittest.mock)
# ---------------------------------------------------------------------------


class _MockBackend:
    def __init__(self, name: str, peers: list[PeerRecord]) -> None:
        self.name = name
        self._peers = peers
        self.announced: list[tuple[bytes, bytes, str]] = []
        self.unannounced: list[tuple[bytes, bytes]] = []

    async def announce(
        self,
        mh: bytes,
        aid: bytes,
        role: Literal["seeder", "leecher"],
    ) -> None:
        self.announced.append((mh, aid, role))

    async def lookup(self, mh: bytes) -> list[PeerRecord]:
        return list(self._peers)

    async def unannounce(self, mh: bytes, aid: bytes) -> None:
        self.unannounced.append((mh, aid))


class _FailingBackend:
    """A backend that raises on every call."""

    def __init__(self, name: str = "failing") -> None:
        self.name = name

    async def announce(
        self,
        mh: bytes,
        aid: bytes,
        role: Literal["seeder", "leecher"],
    ) -> None:
        raise RuntimeError("announce boom")

    async def lookup(self, mh: bytes) -> list[PeerRecord]:
        raise RuntimeError("lookup boom")

    async def unannounce(self, mh: bytes, aid: bytes) -> None:
        raise RuntimeError("unannounce boom")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peer(agent_id: bytes, role: str = "seeder", last_seen: float = 0.0) -> PeerRecord:
    return PeerRecord(agent_id=agent_id, role=role, last_seen=last_seen, source="mock")


def _find(ranked: list[RankedPeer], agent_id: bytes) -> RankedPeer:
    for rp in ranked:
        if rp.record.agent_id == agent_id:
            return rp
    raise AssertionError(f"peer {agent_id.hex()} not found in ranked list")


# ---------------------------------------------------------------------------
# Trust scoring
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_single_backend_all_medium_trust() -> None:
    """One backend — all peers are assigned MEDIUM trust."""
    now = time.time()
    b1 = _MockBackend("b1", [_peer(_PEER_A, last_seen=now)])
    dc = DiscoveryClient([b1])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 1
    assert ranked[0].trust == TrustLevel.MEDIUM
    assert ranked[0].record.agent_id == _PEER_A


@pytest.mark.unit
async def test_three_backends_all_agree_high_trust() -> None:
    """All 3 backends return the same peer -> HIGH trust."""
    now = time.time()
    peer = _peer(_PEER_A, last_seen=now)
    backends = [_MockBackend(f"b{i}", [peer]) for i in range(3)]
    dc = DiscoveryClient(backends)

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 1
    assert ranked[0].trust == TrustLevel.HIGH
    assert ranked[0].corroborated_by == 3


@pytest.mark.unit
async def test_three_backends_majority_medium_trust() -> None:
    """2 of 3 backends return the peer -> MEDIUM trust."""
    now = time.time()
    peer = _peer(_PEER_A, last_seen=now)
    b1 = _MockBackend("b1", [peer])
    b2 = _MockBackend("b2", [peer])
    b3 = _MockBackend("b3", [])  # does not return this peer
    dc = DiscoveryClient([b1, b2, b3])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 1
    assert ranked[0].trust == TrustLevel.MEDIUM
    assert ranked[0].corroborated_by == 2


@pytest.mark.unit
async def test_three_backends_one_only_low_trust() -> None:
    """Only 1 of 3 backends returns the peer -> LOW trust."""
    now = time.time()
    peer = _peer(_PEER_A, last_seen=now)
    b1 = _MockBackend("b1", [peer])
    b2 = _MockBackend("b2", [])
    b3 = _MockBackend("b3", [])
    dc = DiscoveryClient([b1, b2, b3])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 1
    assert ranked[0].trust == TrustLevel.LOW
    assert ranked[0].corroborated_by == 1


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_ranking_seeders_before_leechers() -> None:
    """At the same trust level, seeders are ranked before leechers."""
    now = time.time()
    seeder = _peer(_PEER_A, role="seeder", last_seen=now)
    leecher = _peer(_PEER_B, role="leecher", last_seen=now)
    b1 = _MockBackend("b1", [leecher, seeder])  # deliberate reverse order
    dc = DiscoveryClient([b1])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 2
    assert ranked[0].record.agent_id == _PEER_A  # seeder first
    assert ranked[0].record.role == "seeder"
    assert ranked[1].record.agent_id == _PEER_B
    assert ranked[1].record.role == "leecher"


@pytest.mark.unit
async def test_ranking_by_recency() -> None:
    """Within same trust and role, newer last_seen is ranked first."""
    old = _peer(_PEER_A, role="seeder", last_seen=1000.0)
    new = _peer(_PEER_B, role="seeder", last_seen=2000.0)
    b1 = _MockBackend("b1", [old, new])
    dc = DiscoveryClient([b1])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 2
    assert ranked[0].record.agent_id == _PEER_B  # newer first
    assert ranked[1].record.agent_id == _PEER_A


# ---------------------------------------------------------------------------
# announce / unannounce broadcast
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_announce_calls_all_backends() -> None:
    backends = [_MockBackend(f"b{i}", []) for i in range(3)]
    dc = DiscoveryClient(backends)

    await dc.announce(_MH, _PEER_A, "seeder")

    for b in backends:
        assert len(b.announced) == 1
        mh, aid, role = b.announced[0]
        assert mh == _MH
        assert aid == _PEER_A
        assert role == "seeder"


@pytest.mark.unit
async def test_unannounce_calls_all_backends() -> None:
    backends = [_MockBackend(f"b{i}", []) for i in range(3)]
    dc = DiscoveryClient(backends)

    await dc.unannounce(_MH, _PEER_A)

    for b in backends:
        assert len(b.unannounced) == 1
        mh, aid = b.unannounced[0]
        assert mh == _MH
        assert aid == _PEER_A


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_backend_failure_handled() -> None:
    """One backend raises, the other still returns results."""
    now = time.time()
    good = _MockBackend("good", [_peer(_PEER_A, last_seen=now)])
    bad = _FailingBackend("bad")
    dc = DiscoveryClient([good, bad])

    ranked = await dc.lookup(_MH)

    assert len(ranked) == 1
    assert ranked[0].record.agent_id == _PEER_A


@pytest.mark.unit
async def test_all_backends_fail() -> None:
    """All backends raise -> empty list, no crash."""
    bad1 = _FailingBackend("bad1")
    bad2 = _FailingBackend("bad2")
    dc = DiscoveryClient([bad1, bad2])

    ranked = await dc.lookup(_MH)

    assert ranked == []
