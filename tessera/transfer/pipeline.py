"""Request Pipeline — concurrency control, timeouts, and retry tracking.

Spec: ts-spec-008 §5

The pipeline enforces two concurrency limits via asyncio.Semaphore:
  - max_requests_per_peer  (per peer per swarm, default 5)
  - max_requests_per_swarm (per swarm total, default 20)

It does NOT send wire messages — the Swarm Manager (Phase 5) hooks into
the pipeline by acquiring semaphore slots and registering response futures.
This keeps the pipeline independently testable.

Request lifecycle: QUEUED → IN_FLIGHT → RESOLVED → (COMPLETE | RE_QUEUE)
                                  ↓
                               FAILED → re-queue

Retry policy mirrors ts-spec-008 §5. The pipeline tracks per-tessera
retry counts and raises MaxRetriesExceeded when the limit is hit.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum


class RequestState(Enum):
    QUEUED = "QUEUED"
    IN_FLIGHT = "IN_FLIGHT"
    RESOLVED = "RESOLVED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    RE_QUEUE = "RE_QUEUE"


@dataclass
class InFlightRecord:
    index: int
    peer_id: bytes
    issued_at: float = field(default_factory=time.monotonic)
    attempt: int = 0
    state: RequestState = RequestState.IN_FLIGHT


class MaxRetriesExceeded(Exception):
    """Tessera exhausted all retry attempts."""

    def __init__(self, index: int, attempts: int) -> None:
        super().__init__(f"tessera {index} exhausted {attempts} attempts")
        self.index = index
        self.attempts = attempts


class RequestPipeline:
    """Concurrency control and timeout tracking for in-flight piece requests.

    Args:
        max_per_peer: Per-peer in-flight limit.
        max_per_swarm: Per-swarm total in-flight limit.
        request_timeout: Seconds before a request is considered timed out.
        max_retries: Maximum retry attempts per tessera before marking stuck.
    """

    def __init__(
        self,
        max_per_peer: int = 5,
        max_per_swarm: int = 20,
        request_timeout: float = 30.0,
        max_retries: int = 10,
    ) -> None:
        self._swarm_sem = asyncio.Semaphore(max_per_swarm)
        self._peer_sems: dict[bytes, asyncio.Semaphore] = {}
        self._max_per_peer = max_per_peer
        self._timeout = request_timeout
        self._max_retries = max_retries
        self._in_flight: dict[int, InFlightRecord] = {}
        self._retry_counts: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Semaphore management
    # ------------------------------------------------------------------

    def _peer_sem(self, peer_id: bytes) -> asyncio.Semaphore:
        if peer_id not in self._peer_sems:
            self._peer_sems[peer_id] = asyncio.Semaphore(self._max_per_peer)
        return self._peer_sems[peer_id]

    async def acquire(self, peer_id: bytes, index: int) -> InFlightRecord:
        """Acquire both semaphores and register the request as IN_FLIGHT.

        Raises:
            MaxRetriesExceeded: If this tessera has already been tried
                                max_retries times.
        """
        attempts = self._retry_counts.get(index, 0)
        if attempts >= self._max_retries:
            raise MaxRetriesExceeded(index, attempts)

        await self._swarm_sem.acquire()
        try:
            await self._peer_sem(peer_id).acquire()
        except BaseException:
            self._swarm_sem.release()
            raise

        self._retry_counts[index] = attempts + 1
        record = InFlightRecord(index=index, peer_id=peer_id, attempt=attempts)
        self._in_flight[index] = record
        return record

    def release(self, record: InFlightRecord) -> None:
        """Release both semaphores for a completed or failed request."""
        self._in_flight.pop(record.index, None)
        self._swarm_sem.release()
        sem = self._peer_sems.get(record.peer_id)
        if sem is not None:
            sem.release()

    # ------------------------------------------------------------------
    # Timeout detection
    # ------------------------------------------------------------------

    def timed_out_requests(self) -> list[InFlightRecord]:
        """Return records whose elapsed time exceeds request_timeout."""
        now = time.monotonic()
        return [
            r
            for r in self._in_flight.values()
            if now - r.issued_at >= self._timeout
        ]

    # ------------------------------------------------------------------
    # Capacity queries
    # ------------------------------------------------------------------

    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def peer_in_flight_count(self, peer_id: bytes) -> int:
        return sum(
            1 for r in self._in_flight.values() if r.peer_id == peer_id
        )

    def retry_count(self, index: int) -> int:
        return self._retry_counts.get(index, 0)

    def stuck_tesserae(self) -> list[int]:
        """Indices that have hit the max retry limit."""
        return [i for i, n in self._retry_counts.items() if n >= self._max_retries]
