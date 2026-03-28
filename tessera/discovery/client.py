"""Discovery Client — multi-source peer lookup with trust scoring.

Spec: ts-spec-007 §6

Queries all configured backends concurrently, merges results, and ranks
peers by how many backends independently corroborated their presence.

Trust levels:
  HIGH   — all backends returned this peer (connected first)
  MEDIUM — majority of backends returned this peer
  LOW    — only one backend returned this peer (low initial score)

When only one backend is configured, all peers are treated as MEDIUM trust.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from tessera.discovery.backend import DiscoveryBackend, PeerRecord

log = logging.getLogger(__name__)

_BACKEND_TIMEOUT: float = 10.0  # per-backend lookup timeout


class TrustLevel(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class RankedPeer:
    record: PeerRecord
    trust: TrustLevel
    corroborated_by: int  # number of backends that returned this peer


class DiscoveryClient:
    """Aggregate multiple discovery backends with multi-source verification.

    Args:
        backends: Ordered list of DiscoveryBackend implementations.
        backend_timeout: Seconds to wait for each backend before treating
                         it as failed for that round (default 10).
    """

    def __init__(
        self,
        backends: Sequence[DiscoveryBackend],
        backend_timeout: float = _BACKEND_TIMEOUT,
    ) -> None:
        self._backends = backends
        self._timeout = backend_timeout

    # ------------------------------------------------------------------
    # announce / unannounce (broadcast to all backends)
    # ------------------------------------------------------------------

    async def announce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
        role: str,
    ) -> None:
        """Announce to all backends concurrently."""
        from typing import Literal

        r: Literal["seeder", "leecher"] = "seeder" if role == "seeder" else "leecher"
        await asyncio.gather(
            *[b.announce(manifest_hash, agent_id, r) for b in self._backends],
            return_exceptions=True,
        )

    async def unannounce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
    ) -> None:
        """Unannounce from all backends concurrently."""
        await asyncio.gather(
            *[b.unannounce(manifest_hash, agent_id) for b in self._backends],
            return_exceptions=True,
        )

    # ------------------------------------------------------------------
    # lookup — multi-source with trust scoring
    # ------------------------------------------------------------------

    async def lookup(self, manifest_hash: bytes) -> list[RankedPeer]:
        """Query all backends and return peers ranked by trust.

        Returns an empty list if all backends fail or return nothing.
        """
        results = await asyncio.gather(
            *[self._lookup_one(b, manifest_hash) for b in self._backends],
            return_exceptions=False,
        )

        # Merge: agent_id → list of backend names that returned it.
        seen: dict[bytes, list[PeerRecord]] = {}
        for backend_results in results:
            for rec in backend_results:
                seen.setdefault(rec.agent_id, []).append(rec)

        n_backends = max(len(self._backends), 1)
        ranked: list[RankedPeer] = []
        for _agent_id, records in seen.items():
            count = len(records)
            # Use the most-recently-seen record.
            best = max(records, key=lambda r: r.last_seen)
            if n_backends == 1:
                trust = TrustLevel.MEDIUM
            elif count == n_backends:
                trust = TrustLevel.HIGH
            elif count > n_backends // 2:
                trust = TrustLevel.MEDIUM
            else:
                trust = TrustLevel.LOW
            ranked.append(RankedPeer(record=best, trust=trust, corroborated_by=count))

        # Sort: HIGH → MEDIUM → LOW, then seeders before leechers, then recency.
        _trust_order = {TrustLevel.HIGH: 0, TrustLevel.MEDIUM: 1, TrustLevel.LOW: 2}
        ranked.sort(
            key=lambda p: (
                _trust_order[p.trust],
                0 if p.record.role == "seeder" else 1,
                -p.record.last_seen,
            )
        )
        return ranked

    async def _lookup_one(
        self,
        backend: DiscoveryBackend,
        manifest_hash: bytes,
    ) -> list[PeerRecord]:
        """Run a single backend lookup with a timeout; return [] on any error."""
        try:
            return await asyncio.wait_for(
                backend.lookup(manifest_hash),
                timeout=self._timeout,
            )
        except Exception:
            log.warning(
                "Backend lookup failed or timed out: %s",
                type(backend).__name__,
                exc_info=True,
            )
            return []
