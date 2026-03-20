"""Merkle tree construction for content addressing.

Spec: ts-spec-006 §3

Rules:
  - Leaves: SHA-256(tessera_data) — computed by the Chunker.
  - Internal nodes: SHA-256(left || right).
  - Odd-node promotion: when a level has an odd number of nodes,
    the last node is promoted as-is. It is NOT duplicated.
  - Empty mosaic: root is 32 zero bytes.
  - Single tessera: root equals the single leaf hash.
"""

from __future__ import annotations

import hashlib

_EMPTY_ROOT: bytes = b"\x00" * 32


def build_root(leaf_hashes: list[bytes]) -> bytes:
    """Compute the Merkle root from a list of 32-byte leaf hashes.

    Args:
        leaf_hashes: SHA-256 hashes of each tessera, in index order.
                     Each must be exactly 32 bytes.

    Returns:
        32-byte Merkle root hash.
    """
    if not leaf_hashes:
        return _EMPTY_ROOT

    level: list[bytes] = list(leaf_hashes)

    while len(level) > 1:
        next_level: list[bytes] = []
        i = 0
        while i < len(level):
            if i + 1 < len(level):
                # Pair: hash concatenation of left and right.
                parent = hashlib.sha256(level[i] + level[i + 1]).digest()
                next_level.append(parent)
                i += 2
            else:
                # Odd node: promote without hashing.
                next_level.append(level[i])
                i += 1
        level = next_level

    return level[0]
