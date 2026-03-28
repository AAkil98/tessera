"""Capacity Enforcer — bounds resources at the per-swarm and per-node level.

Spec: ts-spec-007 §7

Limits:
  max_peers_per_swarm  — per-swarm channel count (default 50)
  max_swarms_per_node  — per-node active swarm count (default 10)

Capacity rebalancing allows the lowest-scoring peer (below
eviction_threshold) to be displaced when a higher-trust newcomer
arrives and the swarm is full.
"""

from __future__ import annotations

from tessera.swarm.registry import SwarmEntry, SwarmRegistry
from tessera.transfer.scorer import PeerScorer


class CapacityEnforcer:
    """Check admission limits and compute rebalancing candidates.

    Args:
        max_peers_per_swarm: Hard per-swarm peer limit (default 50).
        max_swarms_per_node: Hard per-node swarm limit (default 10).
        eviction_threshold: Peers below this score may be displaced (default 0.2).
    """

    def __init__(
        self,
        max_peers_per_swarm: int = 50,
        max_swarms_per_node: int = 10,
        eviction_threshold: float = 0.2,
    ) -> None:
        self._max_peers = max_peers_per_swarm
        self._max_swarms = max_swarms_per_node
        self._eviction_threshold = eviction_threshold

    # ------------------------------------------------------------------
    # Admission checks
    # ------------------------------------------------------------------

    def can_admit_peer(self, entry: SwarmEntry) -> bool:
        """Return True if the swarm has room for one more peer."""
        return len(entry.peers) < self._max_peers

    def can_create_swarm(self, registry: SwarmRegistry) -> bool:
        """Return True if the node has capacity for a new swarm."""
        return registry.active_count() < self._max_swarms

    def capacity_remaining(self, entry: SwarmEntry) -> int:
        """Return how many more peers can join the swarm."""
        return max(0, self._max_peers - len(entry.peers))

    def swarms_remaining(self, registry: SwarmRegistry) -> int:
        """Return how many more swarms can be created on this node."""
        return max(0, self._max_swarms - registry.active_count())

    # ------------------------------------------------------------------
    # Capacity rebalancing
    # ------------------------------------------------------------------

    def displacement_candidate(
        self,
        entry: SwarmEntry,
        scorer: PeerScorer,
    ) -> bytes | None:
        """Return the AgentId of the lowest-scoring displaceable peer.

        A peer is displaceable if its score is below *eviction_threshold*.
        Returns None if no such peer exists (swarm full but no weak peer).
        """
        candidates = [
            pid
            for pid in entry.peers
            if scorer.has_peer(pid) and scorer.score(pid) < self._eviction_threshold
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda pid: scorer.score(pid))
