"""Request Scheduler — piece selection and peer assignment.

Spec: ts-spec-008 §2–3

Selection is driven by the SelectionStrategy protocol (default:
RarestFirstStrategy). Three operating sub-modes:

  Random bootstrap   First initial_random_count selections are random.
  Rarest-first       Default; sorts by ascending availability count.
  Sequential         Falls back when only 1 peer is connected or when
                     fewer than sequential_threshold pieces remain.

The EndgameManager (transfer/endgame.py) tracks the NORMAL/ENDGAME
mode transition. In ENDGAME the caller may request from multiple peers
per piece; the scheduler itself just reports the mode and provides the
remaining-piece list.
"""

from __future__ import annotations

import random as _random_module
from typing import Protocol, runtime_checkable

from tessera.content.bitfield import Bitfield
from tessera.transfer.endgame import EndgameManager
from tessera.types import TransferMode

# Default constants (ts-spec-010 §4)
_DEFAULT_ENDGAME_THRESHOLD: int = 20
_DEFAULT_SEQUENTIAL_THRESHOLD_PCT: float = 0.05
_DEFAULT_SEQUENTIAL_MIN: int = 10
_DEFAULT_INITIAL_RANDOM_COUNT: int = 4


# ---------------------------------------------------------------------------
# SelectionStrategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SelectionStrategy(Protocol):
    """Extension point for alternative piece selection algorithms.

    Spec: ts-spec-008 §2
    """

    def select(
        self,
        needed: set[int],
        availability: dict[int, int],
        peer_bitfields: dict[bytes, set[int]],
        count: int,
    ) -> list[int]:
        """Return up to *count* tessera indices to request next.

        Args:
            needed: Indices not yet held locally and not in-flight.
            availability: tessera index → number of peers holding it.
            peer_bitfields: peer AgentId → set of tessera indices held.
            count: Maximum number of indices to return.

        Returns:
            Ordered list, highest priority first.
        """
        ...


# ---------------------------------------------------------------------------
# Default implementation: rarest-first
# ---------------------------------------------------------------------------


class RarestFirstStrategy:
    """Sort needed tesserae by ascending peer-availability count.

    Ties are broken by index (lower index first) for determinism.
    Only indices held by at least one connected peer are returned.
    """

    def select(
        self,
        needed: set[int],
        availability: dict[int, int],
        peer_bitfields: dict[bytes, set[int]],
        count: int,
    ) -> list[int]:
        # Restrict to pieces at least one peer has.
        reachable = needed & set(availability)
        candidates = sorted(
            reachable,
            key=lambda i: (availability.get(i, 0), i),
        )
        return candidates[:count]


# ---------------------------------------------------------------------------
# RequestScheduler
# ---------------------------------------------------------------------------


class RequestScheduler:
    """Manage piece selection state for one mosaic transfer.

    The scheduler does NOT send messages — that is the pipeline's job.
    It exposes ``select(count)`` which returns the next tessera indices
    to request, and mutation helpers to track what has been received or
    placed in-flight.

    Args:
        tessera_count: Total tesserae in the mosaic.
        local_bitfield: Initially-held pieces (often all-zero for a fetcher).
        endgame_threshold: Remaining-piece count to enter endgame (default 20).
        sequential_threshold_pct: Remaining fraction below which sequential
            selection is used (default 5 %, minimum 10 pieces).
        initial_random_count: Number of random selections before rarest-first
            kicks in (bootstrap diversity, default 4).
        strategy: Piece-selection strategy. Defaults to RarestFirstStrategy.
        rng: Injectable random source for testing.
    """

    def __init__(
        self,
        tessera_count: int,
        local_bitfield: Bitfield | None = None,
        endgame_threshold: int = _DEFAULT_ENDGAME_THRESHOLD,
        sequential_threshold_pct: float = _DEFAULT_SEQUENTIAL_THRESHOLD_PCT,
        initial_random_count: int = _DEFAULT_INITIAL_RANDOM_COUNT,
        strategy: SelectionStrategy | None = None,
        rng: _random_module.Random | None = None,
    ) -> None:
        self._total = tessera_count
        self._local_bf: Bitfield = local_bitfield or Bitfield(tessera_count)
        self._peer_bitfields: dict[bytes, set[int]] = {}
        self._in_flight: set[int] = set()
        self._requests_issued: int = 0
        self._endgame_threshold = endgame_threshold
        self._sequential_threshold = max(
            _DEFAULT_SEQUENTIAL_MIN,
            int(sequential_threshold_pct * tessera_count),
        )
        self._initial_random_count = initial_random_count
        self._strategy: SelectionStrategy = strategy or RarestFirstStrategy()
        self._rng = rng or _random_module.Random()
        self._endgame = EndgameManager(endgame_threshold=endgame_threshold)

    # ------------------------------------------------------------------
    # State mutations
    # ------------------------------------------------------------------

    def update_peer_bitfield(self, peer_id: bytes, indices: set[int]) -> None:
        """Register or replace a peer's piece availability."""
        self._peer_bitfields[peer_id] = indices

    def remove_peer(self, peer_id: bytes) -> None:
        self._peer_bitfields.pop(peer_id, None)

    def mark_received(self, index: int) -> None:
        """Mark *index* as locally held after successful verification."""
        self._local_bf.set(index)
        self._in_flight.discard(index)

    def mark_in_flight(self, index: int) -> None:
        """Record that a REQUEST has been issued for *index*."""
        self._in_flight.add(index)
        self._requests_issued += 1

    def mark_failed(self, index: int) -> None:
        """Remove *index* from in-flight (timeout or reject — re-queue)."""
        self._in_flight.discard(index)

    # ------------------------------------------------------------------
    # Mode query
    # ------------------------------------------------------------------

    @property
    def mode(self) -> TransferMode:
        needed = self._needed()
        unscheduled = len(needed - self._in_flight)
        self._endgame.update(len(needed), unscheduled)
        return self._endgame.mode

    @property
    def remaining(self) -> int:
        return len(self._needed())

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, count: int) -> list[int]:
        """Return up to *count* tessera indices to request next.

        Applies one of three sub-modes depending on swarm state:
        random bootstrap → sequential → rarest-first.
        """
        needed = self._needed()
        if not needed:
            return []

        n_peers = len(self._peer_bitfields)
        remaining = len(needed)
        not_in_flight = needed - self._in_flight

        # --- Mode selection ---
        if n_peers <= 1 or remaining < self._sequential_threshold:
            # Sequential: index order, exclude in-flight.
            result = sorted(not_in_flight)[:count]

        elif self._requests_issued < self._initial_random_count:
            # Random bootstrap: pick from reachable pieces.
            reachable = list(not_in_flight & self._union_peer_pieces())
            k = min(count, len(reachable))
            result = self._rng.sample(reachable, k) if k > 0 else []

        else:
            # Rarest-first via pluggable strategy.
            result = self._strategy.select(
                not_in_flight,
                self._availability(),
                self._peer_bitfields,
                count,
            )

        # Update endgame mode.
        unscheduled = len(not_in_flight) - len(result)
        self._endgame.update(remaining, max(unscheduled, 0))

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _needed(self) -> set[int]:
        """Indices not yet held locally."""
        return {i for i in range(self._total) if not self._local_bf.get(i)}

    def _availability(self) -> dict[int, int]:
        """tessera index → count of peers that hold it."""
        counts: dict[int, int] = {}
        for pieces in self._peer_bitfields.values():
            for i in pieces:
                counts[i] = counts.get(i, 0) + 1
        return counts

    def _union_peer_pieces(self) -> set[int]:
        """Union of all pieces held by any connected peer."""
        result: set[int] = set()
        for pieces in self._peer_bitfields.values():
            result |= pieces
        return result
