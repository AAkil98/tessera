"""Integration tests for Phase 5: swarm registry, capacity, discovery, tracker.

Exit criteria (ts-spec-007):
  - Can create a swarm, admit peers through HANDSHAKE → BITFIELD flow.
  - Bad peers evicted; capacity limits enforced.
  - TrackerBackend works against a mock HTTP client.
  - DiscoveryClient aggregates multi-source results with trust scoring.
"""

from __future__ import annotations

import time

import pytest

from tessera.discovery.backend import PeerRecord
from tessera.discovery.client import DiscoveryClient, TrustLevel
from tessera.discovery.tracker import TrackerBackend
from tessera.swarm.capacity import CapacityEnforcer
from tessera.swarm.partition import PartitionDetector, StarvationTracker
from tessera.swarm.registry import SwarmRegistry
from tessera.transfer.scorer import PeerScorer
from tessera.types import SwarmState

_HASH = b"\xaa" * 32
_PEER_A = b"\x01" * 32
_PEER_B = b"\x02" * 32
_PEER_C = b"\x03" * 32


# ---------------------------------------------------------------------------
# Swarm Registry
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_registry_create_and_transition() -> None:
    reg = SwarmRegistry()
    entry = reg.create(_HASH, role="leecher")
    assert entry.state == SwarmState.PENDING

    # Cannot skip states.
    with pytest.raises(ValueError):
        reg.transition(_HASH, SwarmState.CLOSED)

    reg.transition(_HASH, SwarmState.DRAINING)
    reg.transition(_HASH, SwarmState.CLOSED)
    assert reg.get(_HASH).state == SwarmState.CLOSED


@pytest.mark.integration
def test_registry_add_peer_activates_swarm() -> None:
    from tessera.swarm.registry import PeerInfo

    reg = SwarmRegistry()
    reg.create(_HASH, role="leecher")
    peer = PeerInfo(agent_id=_PEER_A, channel_id=b"\x00" * 4, role="seeder")
    reg.add_peer(_HASH, peer)
    assert reg.get(_HASH).state == SwarmState.ACTIVE


@pytest.mark.integration
def test_registry_blocklist() -> None:
    from tessera.swarm.registry import PeerInfo

    reg = SwarmRegistry()
    reg.create(_HASH, role="leecher")
    peer = PeerInfo(agent_id=_PEER_A, channel_id=b"\x00" * 4, role="seeder")
    reg.add_peer(_HASH, peer)
    reg.blocklist_peer(_HASH, _PEER_A)
    assert reg.is_blocklisted(_HASH, _PEER_A)
    assert not reg.is_blocklisted(_HASH, _PEER_B)


@pytest.mark.integration
def test_registry_active_count() -> None:
    reg = SwarmRegistry()
    assert reg.active_count() == 0
    reg.create(_HASH, role="seeder")
    assert reg.active_count() == 1
    reg.transition(_HASH, SwarmState.DRAINING)
    assert reg.active_count() == 0  # DRAINING not counted


# ---------------------------------------------------------------------------
# Capacity Enforcer
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_capacity_peer_limit() -> None:
    from tessera.swarm.registry import PeerInfo

    reg = SwarmRegistry()
    cap = CapacityEnforcer(max_peers_per_swarm=2)
    reg.create(_HASH, role="leecher")
    entry = reg.get(_HASH)

    assert cap.can_admit_peer(entry)
    reg.add_peer(_HASH, PeerInfo(_PEER_A, b"\x01", "seeder"))
    assert cap.can_admit_peer(entry)
    reg.add_peer(_HASH, PeerInfo(_PEER_B, b"\x02", "seeder"))
    assert not cap.can_admit_peer(entry)


@pytest.mark.integration
def test_capacity_swarm_limit() -> None:
    reg = SwarmRegistry()
    cap = CapacityEnforcer(max_swarms_per_node=2)
    assert cap.can_create_swarm(reg)
    reg.create(b"\xaa" * 32, role="seeder")
    reg.create(b"\xbb" * 32, role="seeder")
    assert not cap.can_create_swarm(reg)


@pytest.mark.integration
def test_capacity_displacement_candidate() -> None:
    from tessera.swarm.registry import PeerInfo

    reg = SwarmRegistry()
    cap = CapacityEnforcer(max_peers_per_swarm=2, eviction_threshold=0.2)
    scorer = PeerScorer()
    reg.create(_HASH, role="leecher")
    entry = reg.get(_HASH)

    reg.add_peer(_HASH, PeerInfo(_PEER_A, b"\x01", "seeder"))
    reg.add_peer(_HASH, PeerInfo(_PEER_B, b"\x02", "seeder"))
    scorer.add_peer(_PEER_A)
    scorer.add_peer(_PEER_B)
    # Drive PEER_A score below eviction_threshold (0.2).
    for _ in range(6):
        scorer.on_hash_mismatch(_PEER_A)

    candidate = cap.displacement_candidate(entry, scorer)
    assert candidate == _PEER_A


# ---------------------------------------------------------------------------
# PartitionDetector
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_partition_keepalive_timeout() -> None:
    det = PartitionDetector(keep_alive_interval=0.05, keep_alive_multiplier=2)
    det.register_peer(_PEER_A)
    # Force the last_seen to be in the past.
    det._last_seen[_PEER_A] = time.monotonic() - 1.0
    assert _PEER_A in det.dead_peers()


@pytest.mark.integration
def test_partition_message_resets_timer() -> None:
    det = PartitionDetector(keep_alive_interval=0.01)
    det.register_peer(_PEER_A)
    det._last_seen[_PEER_A] = time.monotonic() - 1.0
    det.on_message(_PEER_A)  # resets timer
    assert _PEER_A not in det.dead_peers()


@pytest.mark.integration
def test_partition_consecutive_timeouts() -> None:
    det = PartitionDetector(max_consecutive_timeouts=3)
    det.register_peer(_PEER_A)
    assert _PEER_A not in det.dead_peers()
    for _ in range(3):
        det.on_request_timeout(_PEER_A)
    assert _PEER_A in det.dead_peers()


@pytest.mark.integration
def test_starvation_tracker_basic() -> None:
    st = StarvationTracker(starvation_timeout=100.0, backoff_base=1.0)
    st.on_peer_count(0)
    assert st.should_rediscover()  # immediate first attempt
    st.record_rediscovery()
    assert not st.should_rediscover()  # backoff in effect
    assert not st.is_starved()
    # Simulate elapsed time.
    st._zero_since = time.monotonic() - 101.0
    assert st.is_starved()


# ---------------------------------------------------------------------------
# DiscoveryClient — multi-source trust scoring
# ---------------------------------------------------------------------------


class _MockBackend:
    def __init__(self, name: str, peers: list[PeerRecord]) -> None:
        self.name = name
        self._peers = peers

    async def announce(self, *_: object) -> None:
        pass

    async def lookup(self, manifest_hash: bytes) -> list[PeerRecord]:
        return self._peers

    async def unannounce(self, *_: object) -> None:
        pass


@pytest.mark.integration
async def test_discovery_client_single_backend() -> None:
    """Single backend → all peers are MEDIUM trust."""
    peers = [
        PeerRecord(agent_id=_PEER_A, role="seeder", last_seen=time.time()),
        PeerRecord(agent_id=_PEER_B, role="leecher", last_seen=time.time()),
    ]
    client = DiscoveryClient([_MockBackend("b1", peers)])
    ranked = await client.lookup(_HASH)
    assert len(ranked) == 2
    assert all(r.trust == TrustLevel.MEDIUM for r in ranked)
    # Seeders before leechers.
    assert ranked[0].record.role == "seeder"


@pytest.mark.integration
async def test_discovery_client_multi_source_trust() -> None:
    """Peer corroborated by all 3 backends → HIGH trust."""
    peers_a = [
        PeerRecord(_PEER_A, "seeder", time.time()),
        PeerRecord(_PEER_B, "leecher", time.time()),
    ]
    peers_b = [
        PeerRecord(_PEER_A, "seeder", time.time()),
        PeerRecord(_PEER_C, "seeder", time.time()),
    ]
    peers_c = [
        PeerRecord(_PEER_A, "seeder", time.time()),
    ]
    client = DiscoveryClient([
        _MockBackend("b1", peers_a),
        _MockBackend("b2", peers_b),
        _MockBackend("b3", peers_c),
    ])
    ranked = await client.lookup(_HASH)
    by_id = {r.record.agent_id: r for r in ranked}
    assert by_id[_PEER_A].trust == TrustLevel.HIGH
    assert by_id[_PEER_B].trust == TrustLevel.LOW
    assert by_id[_PEER_C].trust == TrustLevel.LOW


@pytest.mark.integration
async def test_discovery_client_backend_failure_handled() -> None:
    """A failing backend returns empty; other results still returned."""

    class _FailingBackend:
        async def announce(self, *_: object) -> None:
            pass

        async def lookup(self, manifest_hash: bytes) -> list[PeerRecord]:
            raise ConnectionError("tracker down")

        async def unannounce(self, *_: object) -> None:
            pass

    good = [PeerRecord(_PEER_A, "seeder", time.time())]
    client = DiscoveryClient([
        _FailingBackend(),
        _MockBackend("b2", good),
    ])
    ranked = await client.lookup(_HASH)
    assert len(ranked) == 1
    assert ranked[0].record.agent_id == _PEER_A


# ---------------------------------------------------------------------------
# TrackerBackend against a mock HTTP client
# ---------------------------------------------------------------------------


class _MockHTTPResponse:
    def __init__(self, data: object, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def json(self) -> object:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _MockHTTPClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []
        self.gets: list[dict[str, object]] = []
        self._lookup_resp: list[dict[str, object]] = []

    def set_lookup_response(self, peers: list[dict[str, object]]) -> None:
        self._lookup_resp = peers

    async def post(self, url: str, **kwargs: object) -> _MockHTTPResponse:
        self.posts.append({"url": url, **kwargs})
        return _MockHTTPResponse({"status": "ok"})

    async def get(self, url: str, **kwargs: object) -> _MockHTTPResponse:
        self.gets.append({"url": url, **kwargs})
        return _MockHTTPResponse(self._lookup_resp)

    async def aclose(self) -> None:
        pass


@pytest.mark.integration
async def test_tracker_announce() -> None:
    mock = _MockHTTPClient()
    tracker = TrackerBackend("http://tracker.test", client=mock)
    await tracker.announce(_HASH, _PEER_A, "seeder")
    assert len(mock.posts) == 1
    body = mock.posts[0]["json"]
    assert isinstance(body, dict)
    assert body["manifest_hash"] == _HASH.hex()
    assert body["agent_id"] == _PEER_A.hex()
    assert body["role"] == "seeder"


@pytest.mark.integration
async def test_tracker_lookup() -> None:
    mock = _MockHTTPClient()
    mock.set_lookup_response([
        {"agent_id": _PEER_A.hex(), "role": "seeder", "last_seen": time.time()},
        {"agent_id": _PEER_B.hex(), "role": "leecher", "last_seen": time.time()},
    ])
    tracker = TrackerBackend("http://tracker.test", client=mock)
    peers = await tracker.lookup(_HASH)
    assert len(peers) == 2
    assert peers[0].agent_id == _PEER_A
    assert peers[0].role == "seeder"


@pytest.mark.integration
async def test_tracker_unannounce() -> None:
    mock = _MockHTTPClient()
    tracker = TrackerBackend("http://tracker.test", client=mock)
    await tracker.unannounce(_HASH, _PEER_A)
    assert len(mock.posts) == 1
    body = mock.posts[0]["json"]
    assert isinstance(body, dict)
    assert body["manifest_hash"] == _HASH.hex()


@pytest.mark.integration
async def test_tracker_lookup_empty() -> None:
    mock = _MockHTTPClient()
    mock.set_lookup_response([])
    tracker = TrackerBackend("http://tracker.test", client=mock)
    peers = await tracker.lookup(_HASH)
    assert peers == []


@pytest.mark.integration
async def test_tracker_handles_network_error() -> None:
    """TrackerBackend swallows errors and returns empty on lookup failure."""

    class _BrokenClient:
        async def get(self, url: str, **kwargs: object) -> object:
            raise ConnectionError("network down")

        async def post(self, url: str, **kwargs: object) -> object:
            raise ConnectionError("network down")

        async def aclose(self) -> None:
            pass

    tracker = TrackerBackend("http://tracker.test", client=_BrokenClient())
    # Should not raise.
    peers = await tracker.lookup(_HASH)
    assert peers == []
    await tracker.announce(_HASH, _PEER_A, "seeder")  # no exception
