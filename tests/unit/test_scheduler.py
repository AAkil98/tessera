"""Unit tests for RequestScheduler and EndgameManager — ts-spec-013 §3.3."""

from __future__ import annotations

import random

import pytest

from tessera.content.bitfield import Bitfield
from tessera.transfer.endgame import EndgameManager
from tessera.transfer.scheduler import (
    RarestFirstStrategy,
    RequestScheduler,
    SelectionStrategy,
)
from tessera.types import TransferMode


def _peer(n: int) -> bytes:
    return bytes([n]) * 8


def _scheduler(
    total: int = 20,
    held: list[int] | None = None,
    endgame_threshold: int = 5,
    sequential_threshold_pct: float = 0.05,
    rng: random.Random | None = None,
) -> RequestScheduler:
    bf = Bitfield(total)
    for i in held or []:
        bf.set(i)
    return RequestScheduler(
        tessera_count=total,
        local_bitfield=bf,
        endgame_threshold=endgame_threshold,
        sequential_threshold_pct=sequential_threshold_pct,
        initial_random_count=4,
        rng=rng or random.Random(42),
    )


# ---------------------------------------------------------------------------
# §3.3 — Rarest-first ordering
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rarest_first_ordering() -> None:
    """Needed pieces sorted by ascending availability count."""
    sched = _scheduler(total=10)
    # 3 peers with overlapping coverage.
    sched.update_peer_bitfield(_peer(1), {0, 1, 2, 3, 4, 5, 6, 7, 8, 9})
    sched.update_peer_bitfield(_peer(2), {0, 1, 2, 3, 4})
    sched.update_peer_bitfield(_peer(3), {0, 1, 2})
    # Force past random bootstrap.
    sched._requests_issued = 10

    selected = sched.select(10)
    # Indices 3,4 have availability 2; 5-9 have availability 1.
    # Indices 0,1,2 have availability 3 → rarest are 5-9.
    assert set(selected[:5]).issubset({5, 6, 7, 8, 9})


@pytest.mark.unit
def test_rarest_first_tiebreak() -> None:
    """Ties broken by lower index first."""
    sched = _scheduler(total=5)
    # All pieces available from exactly 1 peer (uniform availability).
    sched.update_peer_bitfield(_peer(1), {0, 1, 2, 3, 4})
    sched._requests_issued = 10

    selected = sched.select(5)
    assert selected == [0, 1, 2, 3, 4]


@pytest.mark.unit
def test_rarest_first_excludes_held() -> None:
    """Pieces already held locally never appear in selection."""
    sched = _scheduler(total=10, held=list(range(6)))
    sched.update_peer_bitfield(_peer(1), set(range(10)))
    sched._requests_issued = 10

    selected = sched.select(10)
    assert set(selected).isdisjoint(set(range(6)))
    assert set(selected).issubset({6, 7, 8, 9})


@pytest.mark.unit
def test_sequential_fallback_single_peer() -> None:
    """Single connected peer → sequential (index order) selection."""
    sched = _scheduler(total=10, sequential_threshold_pct=0.0)
    sched.update_peer_bitfield(_peer(1), set(range(10)))
    sched._requests_issued = 10

    selected = sched.select(5)
    assert selected == [0, 1, 2, 3, 4]


@pytest.mark.unit
def test_sequential_fallback_few_remaining() -> None:
    """≤ sequential_threshold remaining → sequential selection."""
    # 100 pieces, hold 97, 3 remain. threshold = max(10, 5% of 100) = 10 → sequential.
    sched = _scheduler(
        total=100, held=list(range(97)), sequential_threshold_pct=0.05
    )
    sched.update_peer_bitfield(_peer(1), set(range(100)))
    sched.update_peer_bitfield(_peer(2), set(range(100)))
    sched._requests_issued = 10

    selected = sched.select(5)
    # Should return indices 97, 98, 99 in order.
    assert selected == [97, 98, 99]


@pytest.mark.unit
def test_random_first_piece() -> None:
    """First initial_random_count selections draw from available pieces."""
    rng = random.Random(0)
    sched = _scheduler(total=20, rng=rng)
    # Multiple peers so rarest-first would normally apply, but bootstrap kicks in.
    sched.update_peer_bitfield(_peer(1), set(range(20)))
    sched.update_peer_bitfield(_peer(2), set(range(10)))

    # requests_issued == 0 → random bootstrap.
    selected = sched.select(4)
    assert len(selected) == 4
    assert all(0 <= i < 20 for i in selected)
    # All selected pieces must be available from peers.
    available = set(range(20))
    assert set(selected).issubset(available)


@pytest.mark.unit
def test_endgame_activation() -> None:
    """≤ endgame_threshold remaining AND all in-flight → ENDGAME mode."""
    sched = _scheduler(total=10, endgame_threshold=5)
    sched.update_peer_bitfield(_peer(1), set(range(10)))
    sched.update_peer_bitfield(_peer(2), set(range(10)))
    # Hold 5 pieces, 5 remain.
    for i in range(5):
        sched.mark_received(i)
    # Mark all remaining as in-flight.
    for i in range(5, 10):
        sched.mark_in_flight(i)

    assert sched.mode == TransferMode.ENDGAME


@pytest.mark.unit
def test_endgame_not_premature() -> None:
    """Remaining > threshold → NORMAL even if all in-flight."""
    sched = _scheduler(total=20, endgame_threshold=5)
    sched.update_peer_bitfield(_peer(1), set(range(20)))
    # Hold 5, 15 remain, 5 in-flight → not all in-flight, and remaining > threshold.
    for i in range(5):
        sched.mark_received(i)
    for i in range(5, 10):
        sched.mark_in_flight(i)

    assert sched.mode == TransferMode.NORMAL


@pytest.mark.unit
def test_endgame_not_activated_if_not_all_requested() -> None:
    """≤ threshold remaining, but some not yet requested → still NORMAL."""
    sched = _scheduler(total=10, endgame_threshold=5)
    sched.update_peer_bitfield(_peer(1), set(range(10)))
    for i in range(5):
        sched.mark_received(i)
    # Only 3 of the 5 remaining are in-flight.
    for i in range(5, 8):
        sched.mark_in_flight(i)

    assert sched.mode == TransferMode.NORMAL


@pytest.mark.unit
def test_selection_strategy_protocol() -> None:
    """Custom SelectionStrategy is used by the scheduler."""
    returned: list[int] = [3, 7, 1]

    class FixedStrategy:
        def select(
            self,
            needed: set[int],
            availability: dict[int, int],
            peer_bitfields: dict[bytes, set[int]],
            count: int,
        ) -> list[int]:
            return returned[:count]

    assert isinstance(FixedStrategy(), SelectionStrategy)

    sched = RequestScheduler(
        tessera_count=10,
        strategy=FixedStrategy(),
        initial_random_count=0,  # skip random bootstrap
    )
    sched.update_peer_bitfield(_peer(1), set(range(10)))
    sched.update_peer_bitfield(_peer(2), set(range(10)))
    sched._requests_issued = 1

    result = sched.select(2)
    assert result == [3, 7]


# ---------------------------------------------------------------------------
# EndgameManager unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_endgame_manager_activates() -> None:
    em = EndgameManager(endgame_threshold=5)
    em.update(remaining=5, unscheduled=0)
    assert em.mode == TransferMode.ENDGAME


@pytest.mark.unit
def test_endgame_manager_stays_normal_with_unscheduled() -> None:
    em = EndgameManager(endgame_threshold=5)
    em.update(remaining=3, unscheduled=1)
    assert em.mode == TransferMode.NORMAL


@pytest.mark.unit
def test_endgame_manager_zero_remaining_is_normal() -> None:
    em = EndgameManager(endgame_threshold=5)
    em.update(remaining=0, unscheduled=0)
    assert em.mode == TransferMode.NORMAL


@pytest.mark.unit
def test_rarest_first_strategy_protocol() -> None:
    assert isinstance(RarestFirstStrategy(), SelectionStrategy)
