"""Shared public types used across Tessera modules.

Spec: ts-spec-008 §7, ts-spec-010 §4
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ManifestInfo:
    """Parsed representation of a Tessera manifest (ts-spec-006 §4).

    Produced by ManifestParser; consumed by the Transfer Engine,
    Storage Layer, and Intelligence Bridge.
    """

    manifest_hash: bytes
    """SHA-256 of the serialized manifest bytes — the mosaic's identity."""

    root_hash: bytes
    """Merkle root hash stored in the manifest header."""

    tessera_count: int
    """Number of tesserae in the mosaic."""

    tessera_size: int
    """Default tessera size in bytes (all except possibly the last)."""

    file_size: int
    """Original file size in bytes."""

    last_tessera_size: int
    """Actual size of the final tessera (may equal tessera_size)."""

    metadata: dict[str, str]
    """Key-value metadata embedded in the manifest."""

    leaf_hashes: list[bytes]
    """SHA-256 hash of each tessera, in index order (length = tessera_count)."""


class SwarmState(Enum):
    """Lifecycle states of a swarm (ts-spec-007 §2)."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"


class TransferMode(Enum):
    """Request Scheduler operating mode (ts-spec-008 §6)."""

    NORMAL = "NORMAL"
    ENDGAME = "ENDGAME"


@dataclass
class PeerStatus:
    """Per-peer metrics snapshot (ts-spec-008 §7)."""

    agent_id: bytes
    score: float
    latency_ms: float
    failure_rate: float
    bytes_delivered: int
    hash_mismatches: int
    in_flight: int


@dataclass
class TransferStatus:
    """Full transfer status snapshot returned by TesseraNode.status() (ts-spec-008 §7)."""

    manifest_hash: bytes
    state: SwarmState
    mode: TransferMode
    progress: float
    bytes_received: int
    bytes_total: int
    throughput_bps: float
    eta_seconds: float | None
    tesserae_verified: int
    tesserae_total: int
    tesserae_in_flight: int
    stuck_tesserae: list[int]
    peers: list[PeerStatus]


@dataclass
class AIStatus:
    """Status snapshot for the Intelligence Bridge (ts-spec-009 §8)."""

    active: bool
    calls_total: int = 0
    calls_failed: int = 0
    last_success: float | None = None
    last_failure: float | None = None
    circuit_breaker_open: bool = False


@dataclass
class NodeStatus:
    """Overall node status (ts-spec-010 §2)."""

    agent_id: bytes
    active_swarms: int
    total_peers: int
    capacity_remaining: int
    ai: AIStatus | None


@dataclass
class DiscoveryResult:
    """One result from a natural-language query (ts-spec-009 §3)."""

    manifest_hash: bytes
    name: str
    relevance_score: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ManifestEvent:
    """Payload for on_manifest_created / on_manifest_received (ts-spec-010 §6)."""

    manifest_hash: bytes
    file_path: str  # str so it serialises cleanly; callers cast to Path
    file_size: int
    tessera_count: int
    metadata: dict[str, str]


@dataclass
class TransferCompleteEvent:
    """Payload for on_transfer_complete (ts-spec-010 §6)."""

    manifest_hash: bytes
    output_path: str
    file_size: int
    elapsed: float
    peers_used: int
    average_throughput: float


@dataclass
class WatchHandle:
    """Handle returned by ``TesseraNode.watch()``. Call ``cancel()`` to stop."""

    _task: asyncio.Task[None]

    async def cancel(self) -> None:
        """Stop the watch polling loop."""
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
