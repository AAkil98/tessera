"""Chunker — splits a file into fixed-size tesserae.

Spec: ts-spec-006 §2

Default algorithm: FixedSizeChunking.
Extension point: ChunkingStrategy protocol.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from tessera.errors import ConfigError

# MFP PIECE message overhead: 1 byte msg_type + 4 bytes index.
_PIECE_OVERHEAD: int = 5


@runtime_checkable
class ChunkingStrategy(Protocol):
    """Extension point for alternative chunking algorithms (ts-spec-006 §2)."""

    def chunk(self, file_path: Path, tessera_size: int) -> Iterator[bytes]:
        """Yield tessera payloads sequentially from *file_path*."""
        ...

    def tessera_count(self, file_path: Path, tessera_size: int) -> int:
        """Return the number of tesserae without reading the full file."""
        ...


class FixedSizeChunking:
    """Default fixed-size chunking strategy (ts-spec-006 §2).

    All tesserae are exactly *tessera_size* bytes except the final one,
    which holds the remaining bytes (may be shorter). No padding is applied.
    """

    def chunk(self, file_path: Path, tessera_size: int) -> Iterator[bytes]:
        with open(file_path, "rb") as fh:
            while True:
                block = fh.read(tessera_size)
                if not block:
                    break
                yield block

    def tessera_count(self, file_path: Path, tessera_size: int) -> int:
        file_size = file_path.stat().st_size
        if file_size == 0:
            return 0
        return (file_size + tessera_size - 1) // tessera_size


class Chunker:
    """Chunks a file into tesserae and computes per-tessera leaf hashes.

    Args:
        tessera_size: Tessera size in bytes. Must satisfy
                      ``tessera_size + _PIECE_OVERHEAD ≤ max_payload_size``.
        max_payload_size: MFP payload limit (default 1 MiB).
        strategy: Chunking algorithm. Defaults to FixedSizeChunking.
    """

    def __init__(
        self,
        tessera_size: int = 262_144,
        max_payload_size: int = 1_048_576,
        strategy: ChunkingStrategy | None = None,
    ) -> None:
        if tessera_size <= 0:
            raise ConfigError("tessera_size", "must be a positive integer")
        if tessera_size + _PIECE_OVERHEAD > max_payload_size:
            raise ConfigError(
                "tessera_size",
                f"tessera_size ({tessera_size}) + {_PIECE_OVERHEAD} "
                f"exceeds max_payload_size ({max_payload_size})",
            )
        self.tessera_size = tessera_size
        self.max_payload_size = max_payload_size
        self._strategy: ChunkingStrategy = strategy or FixedSizeChunking()

    def chunk(self, file_path: Path) -> Iterator[tuple[int, bytes, bytes]]:
        """Yield ``(index, data, leaf_hash)`` tuples for every tessera.

        *leaf_hash* is ``SHA-256(data)`` — the leaf hash for the Merkle tree.
        The caller is responsible for building the tree (see ``merkle.py``).
        """
        for index, data in enumerate(
            self._strategy.chunk(file_path, self.tessera_size)
        ):
            leaf_hash = hashlib.sha256(data).digest()
            yield index, data, leaf_hash

    def tessera_count(self, file_path: Path) -> int:
        """Return the total tessera count without reading the full file."""
        return self._strategy.tessera_count(file_path, self.tessera_size)

    def last_tessera_size(self, file_path: Path) -> int:
        """Return the byte length of the final tessera."""
        file_size = file_path.stat().st_size
        if file_size == 0:
            return 0
        remainder = file_size % self.tessera_size
        return remainder if remainder != 0 else self.tessera_size
