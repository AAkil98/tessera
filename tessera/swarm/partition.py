"""Network partition detection and starvation handling.

Spec: ts-spec-007 §8

Three detection mechanisms:
  1. MFP channel closure — immediate (handled by caller).
  2. KEEP_ALIVE timeout — if no message in 2×keep_alive_interval (60s).
  3. Request timeout accumulation — after max_consecutive_timeouts (3).

Starvation tracking:
  - When peer count drops to zero, a starvation timer starts.
  - Discovery is retried with exponential backoff (5s → 5min).
  - After starvation_timeout (30 min), raises StarvationError.
"""

from __future__ import annotations

import time
from collections import defaultdict


class PartitionDetector:
    """Detect peer unavailability via KEEP_ALIVE and request timeouts.

    Args:
        keep_alive_interval: Expected interval between peer messages (s).
        keep_alive_multiplier: Timeout = multiplier × interval (default 2).
        max_consecutive_timeouts: Request timeouts before marking dead.
    """

    def __init__(
        self,
        keep_alive_interval: float = 30.0,
        keep_alive_multiplier: float = 2.0,
        max_consecutive_timeouts: int = 3,
    ) -> None:
        self._ka_timeout = keep_alive_interval * keep_alive_multiplier
        self._max_timeouts = max_consecutive_timeouts
        # agent_id → last message timestamp
        self._last_seen: dict[bytes, float] = {}
        # agent_id → consecutive timeout count
        self._timeout_counts: dict[bytes, int] = defaultdict(int)

    def register_peer(self, agent_id: bytes) -> None:
        """Start tracking *agent_id*."""
        self._last_seen[agent_id] = time.monotonic()
        self._timeout_counts[agent_id] = 0

    def forget_peer(self, agent_id: bytes) -> None:
        """Stop tracking *agent_id*."""
        self._last_seen.pop(agent_id, None)
        self._timeout_counts.pop(agent_id, None)

    def on_message(self, agent_id: bytes) -> None:
        """Record any received message from *agent_id* (resets KEEP_ALIVE timer)."""
        self._last_seen[agent_id] = time.monotonic()
        self._timeout_counts[agent_id] = 0

    def on_request_timeout(self, agent_id: bytes) -> None:
        """Record one request timeout for *agent_id*."""
        self._timeout_counts[agent_id] = self._timeout_counts.get(agent_id, 0) + 1

    def dead_peers(self) -> list[bytes]:
        """Return agent_ids presumed dead (KEEP_ALIVE or timeout threshold)."""
        now = time.monotonic()
        dead: list[bytes] = []
        for agent_id, last in self._last_seen.items():
            ka_dead = (now - last) >= self._ka_timeout
            timeout_dead = self._timeout_counts.get(agent_id, 0) >= self._max_timeouts
            if ka_dead or timeout_dead:
                dead.append(agent_id)
        return dead


class StarvationTracker:
    """Detect and report swarm starvation (no peers, no progress).

    Manages exponential backoff for re-discovery and raises StarvationError
    after starvation_timeout seconds with zero peers.

    Args:
        starvation_timeout: Seconds before declaring starvation (default 1800).
        backoff_base: Initial backoff in seconds (default 5).
        backoff_max: Maximum backoff in seconds (default 300 = 5 min).
    """

    def __init__(
        self,
        starvation_timeout: float = 1800.0,
        backoff_base: float = 5.0,
        backoff_max: float = 300.0,
    ) -> None:
        self._timeout = starvation_timeout
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._zero_since: float | None = None
        self._attempt: int = 0
        self._next_rediscover: float = 0.0

    def on_peer_count(self, count: int) -> None:
        """Update starvation state based on current peer count."""
        if count == 0:
            if self._zero_since is None:
                self._zero_since = time.monotonic()
                self._attempt = 0
                self._next_rediscover = 0.0
        else:
            # Peers are connected — not starved.
            self._zero_since = None
            self._attempt = 0

    def should_rediscover(self) -> bool:
        """Return True if it is time to run another discovery lookup."""
        if self._zero_since is None:
            return False
        now = time.monotonic()
        return now >= self._next_rediscover

    def record_rediscovery(self) -> None:
        """Called after a discovery attempt to advance the backoff."""
        self._attempt += 1
        delay = min(
            self._backoff_base * (2 ** (self._attempt - 1)),
            self._backoff_max,
        )
        self._next_rediscover = time.monotonic() + delay

    def is_starved(self) -> bool:
        """Return True if starvation_timeout has elapsed with zero peers."""
        if self._zero_since is None:
            return False
        return (time.monotonic() - self._zero_since) >= self._timeout

    def elapsed(self) -> float:
        """Seconds since the swarm first had zero peers (0 if not starved)."""
        if self._zero_since is None:
            return 0.0
        return time.monotonic() - self._zero_since
