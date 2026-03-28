"""Swarm Registry — tracks all active swarms and their peer lists.

Spec: ts-spec-007 §2

State machine per swarm:
  PENDING → ACTIVE → DRAINING → CLOSED

The Registry is the authoritative in-memory store for swarm state.
It does not perform I/O — persistence is handled by storage/state.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from tessera.errors import TesseraError
from tessera.types import SwarmState


class SwarmNotFoundError(TesseraError):
    """Raised when a swarm lookup fails."""

    def __init__(self, manifest_hash: bytes) -> None:
        super().__init__(f"swarm not found: {manifest_hash[:8].hex()}...")
        self.manifest_hash = manifest_hash


# Valid state transitions.
_TRANSITIONS: dict[SwarmState, set[SwarmState]] = {
    SwarmState.PENDING: {SwarmState.ACTIVE, SwarmState.DRAINING},
    SwarmState.ACTIVE: {SwarmState.DRAINING},
    SwarmState.DRAINING: {SwarmState.CLOSED},
    SwarmState.CLOSED: set(),
}


@dataclass
class PeerInfo:
    """Runtime metadata for one connected peer."""

    agent_id: bytes
    channel_id: bytes
    role: str  # "seeder" | "leecher"
    connected_at: float = field(default_factory=time.monotonic)
    score: float = 0.5


@dataclass
class SwarmEntry:
    """One swarm tracked by the Swarm Registry."""

    manifest_hash: bytes
    state: SwarmState
    role: str  # "seeder" | "leecher" — our local role
    peers: dict[bytes, PeerInfo] = field(default_factory=dict)
    blocklist: set[bytes] = field(default_factory=set)
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None


class SwarmRegistry:
    """Track all active swarms and enforce lifecycle transitions.

    All mutations are synchronous — the Registry is updated inline on
    the asyncio event loop. No I/O is performed here.
    """

    def __init__(self) -> None:
        self._swarms: dict[bytes, SwarmEntry] = {}

    # ------------------------------------------------------------------
    # Swarm lifecycle
    # ------------------------------------------------------------------

    def create(self, manifest_hash: bytes, role: str) -> SwarmEntry:
        """Create a new swarm in PENDING state.

        Raises:
            ValueError: If a swarm for this manifest_hash already exists.
        """
        if manifest_hash in self._swarms:
            raise ValueError(f"swarm already exists for {manifest_hash[:8].hex()}")
        entry = SwarmEntry(
            manifest_hash=manifest_hash,
            state=SwarmState.PENDING,
            role=role,
        )
        self._swarms[manifest_hash] = entry
        return entry

    def get(self, manifest_hash: bytes) -> SwarmEntry:
        """Return the SwarmEntry for *manifest_hash*.

        Raises:
            SwarmNotFoundError: If no swarm exists for this hash.
        """
        if manifest_hash not in self._swarms:
            raise SwarmNotFoundError(manifest_hash)
        return self._swarms[manifest_hash]

    def transition(self, manifest_hash: bytes, new_state: SwarmState) -> SwarmEntry:
        """Advance the swarm to *new_state*.

        Raises:
            SwarmNotFoundError: Swarm not found.
            ValueError: Transition is not permitted from the current state.
        """
        entry = self.get(manifest_hash)
        allowed = _TRANSITIONS[entry.state]
        if new_state not in allowed:
            raise ValueError(
                f"cannot transition swarm {manifest_hash[:8].hex()} "
                f"from {entry.state.value} to {new_state.value}"
            )
        entry.state = new_state
        if new_state == SwarmState.CLOSED:
            entry.completed_at = time.monotonic()
        return entry

    def remove(self, manifest_hash: bytes) -> None:
        """Remove a CLOSED swarm from the registry."""
        entry = self._swarms.get(manifest_hash)
        if entry is not None and entry.state != SwarmState.CLOSED:
            raise ValueError("can only remove CLOSED swarms")
        self._swarms.pop(manifest_hash, None)

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def add_peer(self, manifest_hash: bytes, peer: PeerInfo) -> None:
        """Register *peer* in the swarm."""
        entry = self.get(manifest_hash)
        entry.peers[peer.agent_id] = peer
        # Transition PENDING → ACTIVE on first peer.
        if entry.state == SwarmState.PENDING and entry.peers:
            entry.state = SwarmState.ACTIVE

    def remove_peer(self, manifest_hash: bytes, agent_id: bytes) -> PeerInfo | None:
        """Remove and return the peer entry, or None if not present."""
        entry = self._swarms.get(manifest_hash)
        if entry is None:
            return None
        return entry.peers.pop(agent_id, None)

    def blocklist_peer(self, manifest_hash: bytes, agent_id: bytes) -> None:
        """Add *agent_id* to the per-swarm blocklist."""
        self.get(manifest_hash).blocklist.add(agent_id)

    def is_blocklisted(self, manifest_hash: bytes, agent_id: bytes) -> bool:
        entry = self._swarms.get(manifest_hash)
        return entry is not None and agent_id in entry.blocklist

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_swarms(self) -> list[SwarmEntry]:
        return list(self._swarms.values())

    def active_count(self) -> int:
        """Count swarms that are PENDING or ACTIVE (consuming node capacity)."""
        return sum(
            1
            for e in self._swarms.values()
            if e.state in (SwarmState.PENDING, SwarmState.ACTIVE)
        )

    def has(self, manifest_hash: bytes) -> bool:
        return manifest_hash in self._swarms
