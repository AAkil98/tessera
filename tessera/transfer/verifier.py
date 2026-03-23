"""Piece Verifier — per-tessera SHA-256 integrity check.

Spec: ts-spec-006 §7 Level-2 (per-tessera verification)

Every PIECE message is verified before being written to disk.
A mismatch means the sender served a corrupted or poisoned tessera (T1).
"""

from __future__ import annotations

import hashlib


def verify_piece(data: bytes, leaf_hash: bytes) -> bool:
    """Return True if SHA-256(*data*) matches *leaf_hash*.

    Args:
        data: Raw tessera bytes from a PIECE message.
        leaf_hash: Expected 32-byte SHA-256 hash from the manifest.

    Returns:
        True if the piece is intact; False if it is corrupted / poisoned.
    """
    return hashlib.sha256(data).digest() == leaf_hash


class PieceVerifier:
    """Stateless wrapper around ``verify_piece`` for injection into the pipeline."""

    def verify(self, data: bytes, leaf_hash: bytes) -> bool:
        """Return True if *data* matches *leaf_hash*."""
        return verify_piece(data, leaf_hash)
