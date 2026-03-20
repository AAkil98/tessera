"""Bitfield — compact piece-availability bitmap.

Spec: ts-spec-005 §4 (BITFIELD message payload), ts-spec-013 §3.7

Bit layout: MSB-first. Bit 0 is the most-significant bit of byte 0.
Bit i lives in byte (i // 8), at bit position (7 - i % 8) within that byte.
Trailing bits in the last byte are always zero-padded.
"""

from __future__ import annotations

import base64


class Bitfield:
    """Fixed-length bitfield tracking which tesserae a peer holds.

    Args:
        count: Total number of tesserae (bits) in this bitfield.
        data: Optional initial bytes. Length must be ⌈count/8⌉.
              Defaults to all-zero (nothing held).
    """

    def __init__(self, count: int, data: bytes | None = None) -> None:
        if count < 0:
            raise ValueError(f"count must be non-negative, got {count}")
        self._count = count
        self._byte_len = (count + 7) // 8
        if data is not None:
            if len(data) != self._byte_len:
                raise ValueError(
                    f"data length {len(data)} does not match "
                    f"expected {self._byte_len} for count={count}"
                )
            self._buf = bytearray(data)
        else:
            self._buf = bytearray(self._byte_len)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total number of bits (tesserae) this bitfield tracks."""
        return self._count

    # ------------------------------------------------------------------
    # Bit access
    # ------------------------------------------------------------------

    def get(self, index: int) -> bool:
        """Return True if bit *index* is set."""
        self._check_index(index)
        byte_pos, bit_pos = divmod(index, 8)
        return bool(self._buf[byte_pos] & (0x80 >> bit_pos))

    def set(self, index: int) -> None:
        """Set bit *index* to 1."""
        self._check_index(index)
        byte_pos, bit_pos = divmod(index, 8)
        self._buf[byte_pos] |= 0x80 >> bit_pos

    def clear(self, index: int) -> None:
        """Clear bit *index* to 0."""
        self._check_index(index)
        byte_pos, bit_pos = divmod(index, 8)
        self._buf[byte_pos] &= ~(0x80 >> bit_pos)

    # ------------------------------------------------------------------
    # Aggregate queries
    # ------------------------------------------------------------------

    def count_set(self) -> int:
        """Return the number of bits that are set to 1."""
        return sum(bin(b).count("1") for b in self._buf)

    def is_complete(self) -> bool:
        """Return True when all bits are set (peer holds every tessera)."""
        return self.count_set() == self._count

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialize to ⌈count/8⌉ bytes, MSB-first, trailing bits zero."""
        return bytes(self._buf)

    @classmethod
    def from_bytes(cls, count: int, data: bytes) -> Bitfield:
        """Deserialize from raw bytes produced by ``to_bytes``."""
        return cls(count, data)

    def to_base64(self) -> str:
        """Serialize to URL-safe base64 (used in JSON state files)."""
        return base64.urlsafe_b64encode(self._buf).decode()

    @classmethod
    def from_base64(cls, count: int, encoded: str) -> Bitfield:
        """Deserialize from URL-safe base64 produced by ``to_base64``."""
        data = base64.urlsafe_b64decode(encoded)
        return cls(count, data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_index(self, index: int) -> None:
        if not (0 <= index < self._count):
            raise IndexError(
                f"bit index {index} out of range [0, {self._count})"
            )

    def __repr__(self) -> str:
        return (
            f"Bitfield(count={self._count}, "
            f"set={self.count_set()}, "
            f"bytes={self._buf.hex()})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Bitfield):
            return NotImplemented
        return self._count == other._count and self._buf == other._buf
