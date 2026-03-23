"""Endgame mode — aggressive duplicate requesting for the final tesserae.

Spec: ts-spec-008 §6

Entry criteria (both must be true):
  1. Remaining un-verified tesserae ≤ endgame_threshold.
  2. All remaining tesserae have been requested at least once (nothing
     in the needed-but-not-requested set).

In endgame mode the normal no-duplicate-requests rule is suspended.
The RequestScheduler delegates the mode check here so the logic is
self-contained and independently testable.
"""

from __future__ import annotations

from tessera.types import TransferMode


class EndgameManager:
    """Track whether the scheduler should operate in endgame mode.

    Args:
        endgame_threshold: Maximum remaining pieces to enter endgame.
        max_endgame_requests: Hard cap on total in-flight requests during
            endgame (capped at remaining × peers, default 100).
    """

    def __init__(
        self,
        endgame_threshold: int = 20,
        max_endgame_requests: int = 100,
    ) -> None:
        self._threshold = endgame_threshold
        self._max_endgame = max_endgame_requests
        self._mode = TransferMode.NORMAL

    @property
    def mode(self) -> TransferMode:
        return self._mode

    def update(self, remaining: int, unscheduled: int) -> None:
        """Recompute the mode.

        Args:
            remaining: Number of un-verified tesserae.
            unscheduled: Number of needed tesserae that have NOT yet been
                         requested (i.e. not in-flight).
        """
        if remaining == 0:
            self._mode = TransferMode.NORMAL
            return

        if remaining <= self._threshold and unscheduled == 0:
            self._mode = TransferMode.ENDGAME
        else:
            self._mode = TransferMode.NORMAL

    def endgame_swarm_limit(self, remaining: int, connected_peers: int) -> int:
        """Return the raised per-swarm request limit during endgame.

        Capped at max_endgame_requests.
        """
        return min(remaining * max(connected_peers, 1), self._max_endgame)
