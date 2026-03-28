"""Unit tests for PartitionDetector and StarvationTracker — ts-spec-007 §8."""

from __future__ import annotations

import time

import pytest

from tessera.swarm.partition import PartitionDetector, StarvationTracker


def _peer(n: int) -> bytes:
    return bytes([n]) * 8


# ---------------------------------------------------------------------------
# PartitionDetector — KEEP_ALIVE and request-timeout detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_register_and_forget_peer() -> None:
    """§8: register adds peer to tracking; forget removes it entirely."""
    det = PartitionDetector()
    peer = _peer(1)

    det.register_peer(peer)
    assert peer in det._last_seen
    assert peer in det._timeout_counts

    det.forget_peer(peer)
    assert peer not in det._last_seen
    assert peer not in det._timeout_counts


@pytest.mark.unit
def test_on_message_resets_timer() -> None:
    """§8: any received message resets the KEEP_ALIVE timer and timeout count."""
    det = PartitionDetector(keep_alive_interval=30.0, keep_alive_multiplier=2.0)
    peer = _peer(1)

    det.register_peer(peer)
    # Simulate the peer being silent for well past the 60s timeout.
    det._last_seen[peer] = time.monotonic() - 200.0
    assert peer in det.dead_peers()

    # A message arrives — peer should no longer be dead.
    det.on_message(peer)
    assert peer not in det.dead_peers()


@pytest.mark.unit
def test_dead_peers_after_keepalive_timeout() -> None:
    """§8: peer with no message for >= 2×keep_alive_interval is dead."""
    det = PartitionDetector(keep_alive_interval=10.0, keep_alive_multiplier=2.0)
    peer = _peer(1)

    det.register_peer(peer)
    # Place last_seen 20s+ in the past (timeout = 10 * 2 = 20s).
    det._last_seen[peer] = time.monotonic() - 25.0

    dead = det.dead_peers()
    assert peer in dead


@pytest.mark.unit
def test_dead_peers_none_when_active() -> None:
    """§8: recently registered peer is not dead."""
    det = PartitionDetector(keep_alive_interval=30.0)
    peer = _peer(1)

    det.register_peer(peer)
    assert det.dead_peers() == []


@pytest.mark.unit
def test_on_request_timeout_accumulates() -> None:
    """§8: each request timeout increments the consecutive counter."""
    det = PartitionDetector(max_consecutive_timeouts=5)
    peer = _peer(1)
    det.register_peer(peer)

    det.on_request_timeout(peer)
    det.on_request_timeout(peer)
    det.on_request_timeout(peer)

    assert det._timeout_counts[peer] == 3


@pytest.mark.unit
def test_dead_after_consecutive_timeouts() -> None:
    """§8: peer is dead after max_consecutive_timeouts request timeouts."""
    det = PartitionDetector(
        keep_alive_interval=30.0,
        keep_alive_multiplier=2.0,
        max_consecutive_timeouts=3,
    )
    peer = _peer(1)
    det.register_peer(peer)

    for _ in range(3):
        det.on_request_timeout(peer)

    assert peer in det.dead_peers()


@pytest.mark.unit
def test_timeout_count_resets_on_message() -> None:
    """§8: receiving a message resets the consecutive timeout counter to 0."""
    det = PartitionDetector(max_consecutive_timeouts=3)
    peer = _peer(1)
    det.register_peer(peer)

    det.on_request_timeout(peer)
    det.on_request_timeout(peer)
    assert det._timeout_counts[peer] == 2

    det.on_message(peer)
    assert det._timeout_counts[peer] == 0
    assert peer not in det.dead_peers()


# ---------------------------------------------------------------------------
# StarvationTracker — zero-peer detection and re-discovery backoff
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_starvation_tracker_initial_state() -> None:
    """§8: fresh tracker is not starved and has zero elapsed time."""
    tracker = StarvationTracker()
    assert tracker.is_starved() is False
    assert tracker.elapsed() == 0.0


@pytest.mark.unit
def test_starvation_on_peer_count_zero_starts_timer() -> None:
    """§8: reporting zero peers starts the starvation timer."""
    tracker = StarvationTracker()
    tracker.on_peer_count(0)
    assert tracker.elapsed() > 0.0 or tracker._zero_since is not None


@pytest.mark.unit
def test_starvation_on_peer_count_positive_resets() -> None:
    """§8: reporting positive peer count resets starvation state."""
    tracker = StarvationTracker()
    tracker.on_peer_count(0)
    assert tracker._zero_since is not None

    tracker.on_peer_count(1)
    assert tracker._zero_since is None
    assert tracker.elapsed() == 0.0


@pytest.mark.unit
def test_should_rediscover_immediately_after_zero() -> None:
    """§8: should_rediscover is True immediately after zero-peer notification."""
    tracker = StarvationTracker()
    tracker.on_peer_count(0)
    # _next_rediscover is set to 0.0 on first zero, so current time >= 0.0.
    assert tracker.should_rediscover() is True


@pytest.mark.unit
def test_record_rediscovery_advances_backoff() -> None:
    """§8: after recording a discovery attempt, backoff prevents immediate retry."""
    tracker = StarvationTracker(backoff_base=5.0)
    tracker.on_peer_count(0)
    assert tracker.should_rediscover() is True

    tracker.record_rediscovery()
    # Backoff delay = 5.0 * 2^0 = 5.0s; should_rediscover must be False now.
    assert tracker.should_rediscover() is False


@pytest.mark.unit
def test_is_starved_after_timeout() -> None:
    """§8: is_starved returns True once starvation_timeout has elapsed."""
    timeout = 1800.0
    tracker = StarvationTracker(starvation_timeout=timeout)
    tracker.on_peer_count(0)
    # Manually shift _zero_since into the past by timeout seconds.
    tracker._zero_since = time.monotonic() - timeout - 1.0

    assert tracker.is_starved() is True
