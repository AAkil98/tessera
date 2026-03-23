"""Wire protocol error codes.

Spec: ts-spec-005 §7

Codes are grouped by range:
  0x01xx — Protocol errors (message format, state machine violations)
  0x02xx — Transfer errors (tessera exchange failures)
  0x03xx — Capacity errors (resource limit refusals)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Protocol errors (0x0100–0x01FF)
# ---------------------------------------------------------------------------

UNEXPECTED_MSG: int = 0x0100
"""Message type not valid in the current state (e.g. REQUEST before BITFIELD)."""

DUPLICATE_MSG: int = 0x0101
"""A message that must be sent exactly once was sent again."""

MANIFEST_MISMATCH: int = 0x0102
"""HANDSHAKE manifest_hash does not match the local manifest hash."""

VERSION_MISMATCH: int = 0x0103
"""HANDSHAKE protocol version is not supported."""

MALFORMED_MSG: int = 0x0104
"""Message body could not be parsed for its declared msg_type."""

UNKNOWN_MSG_TYPE: int = 0x0105
"""msg_type is not recognized (reserved or unsupported core range)."""

# ---------------------------------------------------------------------------
# Transfer errors (0x0200–0x02FF)
# ---------------------------------------------------------------------------

INDEX_OUT_OF_RANGE: int = 0x0200
"""Requested tessera index exceeds the mosaic's tessera_count."""

HASH_MISMATCH: int = 0x0201
"""Received PIECE data does not match the manifest leaf hash."""

NOT_AVAILABLE: int = 0x0202
"""Peer does not hold the requested tessera."""

ALREADY_HAVE: int = 0x0203
"""Unsolicited PIECE for a tessera the receiver already holds."""

# ---------------------------------------------------------------------------
# Capacity errors (0x0300–0x03FF)
# ---------------------------------------------------------------------------

OVERLOADED: int = 0x0300
"""Peer cannot serve more requests right now — back off and retry."""

SWARM_FULL: int = 0x0301
"""Swarm has reached max_peers_per_swarm."""

SHUTTING_DOWN: int = 0x0302
"""Peer is in graceful shutdown and will not accept new requests."""
