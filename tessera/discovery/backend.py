"""DiscoveryBackend protocol and PeerRecord.

Spec: ts-spec-007 §4

All discovery implementations (tracker, gossip, etc.) must satisfy this
interface. The Discovery Client (discovery/client.py) delegates to one
or more backends concurrently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass
class PeerRecord:
    """A peer known to participate in a mosaic swarm.

    The ``source`` field is set by the Discovery Client to identify which
    backend returned the record — used for multi-source trust scoring.
    """

    agent_id: bytes
    """32-byte MFP AgentId."""

    role: str
    """'seeder' or 'leecher'."""

    last_seen: float
    """Unix timestamp of the peer's last announce/refresh."""

    source: str = ""
    """Backend name that returned this record (filled in by DiscoveryClient)."""


@runtime_checkable
class DiscoveryBackend(Protocol):
    """Interface all discovery backends must satisfy (ts-spec-007 §4)."""

    async def announce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
        role: Literal["seeder", "leecher"],
    ) -> None:
        """Register this peer in the swarm for *manifest_hash*.

        Idempotent — calling twice with the same args has no extra effect.
        """
        ...

    async def lookup(
        self,
        manifest_hash: bytes,
    ) -> list[PeerRecord]:
        """Return peers known to participate in the swarm for *manifest_hash*.

        Returns an empty list if none found. Must not raise on "not found".
        """
        ...

    async def unannounce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
    ) -> None:
        """Remove this peer from the swarm listing.

        Idempotent — unannouncing a peer that is not listed is a no-op.
        """
        ...
