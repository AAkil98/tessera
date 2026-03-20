"""Shared public types used across Tessera modules.

Richer types (TransferStatus, NodeStatus, AIStatus, etc.) are added
in later phases as the components that produce them are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
