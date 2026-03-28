"""Unit tests for RequestPipeline, InFlightRecord, MaxRetriesExceeded — ts-spec-008 §5."""

from __future__ import annotations

import asyncio
import time

import pytest

from tessera.transfer.pipeline import (
    InFlightRecord,
    MaxRetriesExceeded,
    RequestPipeline,
    RequestState,
)


def _peer(n: int) -> bytes:
    return bytes([n]) * 8


# ---------------------------------------------------------------------------
# InFlightRecord and basic acquire / release
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_acquire_returns_in_flight_record() -> None:
    """§5: acquire returns an InFlightRecord with correct index, peer_id, state."""
    pipe = RequestPipeline()
    peer = _peer(1)

    record = await pipe.acquire(peer, index=7)

    assert isinstance(record, InFlightRecord)
    assert record.index == 7
    assert record.peer_id == peer
    assert record.state == RequestState.IN_FLIGHT


@pytest.mark.unit
async def test_release_decrements_count() -> None:
    """§5: releasing a record removes it from in-flight tracking."""
    pipe = RequestPipeline()
    peer = _peer(1)

    record = await pipe.acquire(peer, index=0)
    assert pipe.in_flight_count() == 1

    pipe.release(record)
    assert pipe.in_flight_count() == 0


@pytest.mark.unit
async def test_in_flight_count_tracks_active() -> None:
    """§5: in_flight_count reflects currently acquired requests."""
    pipe = RequestPipeline()
    peer = _peer(1)

    r0 = await pipe.acquire(peer, index=0)
    r1 = await pipe.acquire(peer, index=1)
    r2 = await pipe.acquire(peer, index=2)

    assert pipe.in_flight_count() == 3

    pipe.release(r0)
    pipe.release(r1)
    pipe.release(r2)


@pytest.mark.unit
async def test_peer_in_flight_count() -> None:
    """§5: peer_in_flight_count tracks per-peer active requests."""
    pipe = RequestPipeline()
    peer_a = _peer(1)
    peer_b = _peer(2)

    await pipe.acquire(peer_a, index=0)
    await pipe.acquire(peer_a, index=1)
    await pipe.acquire(peer_b, index=2)

    assert pipe.peer_in_flight_count(peer_a) == 2
    assert pipe.peer_in_flight_count(peer_b) == 1


# ---------------------------------------------------------------------------
# Timeout detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_timed_out_requests_empty_when_fresh() -> None:
    """§5: freshly acquired requests are not considered timed out."""
    pipe = RequestPipeline(request_timeout=30.0)
    peer = _peer(1)

    await pipe.acquire(peer, index=0)

    assert pipe.timed_out_requests() == []


@pytest.mark.unit
async def test_timed_out_requests_returns_old() -> None:
    """§5: requests whose issued_at is older than request_timeout are returned."""
    pipe = RequestPipeline(request_timeout=10.0)
    peer = _peer(1)

    record = await pipe.acquire(peer, index=0)
    # Shift issued_at 15 seconds into the past.
    record.issued_at = time.monotonic() - 15.0

    timed_out = pipe.timed_out_requests()
    assert len(timed_out) == 1
    assert timed_out[0].index == 0


# ---------------------------------------------------------------------------
# Retry tracking
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_retry_count_increments() -> None:
    """§5: re-acquiring the same index after release increments retry_count."""
    pipe = RequestPipeline()
    peer = _peer(1)

    r1 = await pipe.acquire(peer, index=5)
    pipe.release(r1)
    r2 = await pipe.acquire(peer, index=5)
    pipe.release(r2)

    assert pipe.retry_count(5) == 2


@pytest.mark.unit
async def test_max_retries_exceeded() -> None:
    """§5: exceeding max_retries raises MaxRetriesExceeded."""
    pipe = RequestPipeline(max_retries=2)
    peer = _peer(1)

    r1 = await pipe.acquire(peer, index=3)
    pipe.release(r1)
    r2 = await pipe.acquire(peer, index=3)
    pipe.release(r2)

    with pytest.raises(MaxRetriesExceeded) as exc_info:
        await pipe.acquire(peer, index=3)

    assert exc_info.value.index == 3
    assert exc_info.value.attempts == 2


@pytest.mark.unit
async def test_stuck_tesserae() -> None:
    """§5: indices that hit max_retries appear in stuck_tesserae."""
    pipe = RequestPipeline(max_retries=2)
    peer = _peer(1)

    r1 = await pipe.acquire(peer, index=4)
    pipe.release(r1)
    r2 = await pipe.acquire(peer, index=4)
    pipe.release(r2)

    # Trigger the MaxRetriesExceeded so the count reaches the limit.
    with pytest.raises(MaxRetriesExceeded):
        await pipe.acquire(peer, index=4)

    assert 4 in pipe.stuck_tesserae()


# ---------------------------------------------------------------------------
# Semaphore concurrency limits
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_swarm_semaphore_limits_total() -> None:
    """§5: max_per_swarm limits total concurrent in-flight requests."""
    pipe = RequestPipeline(max_per_swarm=2, max_per_peer=10)
    peer = _peer(1)

    await pipe.acquire(peer, index=0)
    await pipe.acquire(peer, index=1)

    # Third acquire should block because the swarm semaphore is exhausted.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pipe.acquire(peer, index=2), timeout=0.05)


@pytest.mark.unit
async def test_peer_semaphore_limits_per_peer() -> None:
    """§5: max_per_peer limits concurrent in-flight requests per peer."""
    pipe = RequestPipeline(max_per_swarm=10, max_per_peer=1)
    peer = _peer(1)

    await pipe.acquire(peer, index=0)

    # Second acquire for the same peer should block.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pipe.acquire(peer, index=1), timeout=0.05)
