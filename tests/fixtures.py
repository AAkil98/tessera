"""Test data generation helpers.

Provides deterministic byte sequences matching the standard fixture sizes
defined in ts-spec-013 §2:
  empty  — 0 bytes
  tiny   — 1 byte (0x42), exactly as spec specifies
  exact  — 256 KiB (exactly one chunk)
  small  — 1 MiB (four chunks)
  medium — 50 MiB (200 chunks, for E2E tests)
"""

from __future__ import annotations

import random

FIXED_SEED = 42
DEFAULT_CHUNK_SIZE = 256 * 1024  # 256 KiB — matches ts-spec-006

TINY_SIZE = 1  # 1 byte: b'\x42' per ts-spec-013 §2
EXACT_SIZE = DEFAULT_CHUNK_SIZE  # 256 KiB
SMALL_SIZE = DEFAULT_CHUNK_SIZE * 4  # 1 MiB — 4 tesserae
MEDIUM_SIZE = DEFAULT_CHUNK_SIZE * 200  # 50 MiB — 200 tesserae
EMPTY_SIZE = 0


_RANDBYTES_MAX = 128 * 1024 * 1024  # 128 MiB per call (safe for C int limit)


def make_bytes(size: int, seed: int = FIXED_SEED) -> bytes:
    """Return *size* deterministic pseudorandom bytes seeded with *seed*."""
    rng = random.Random(seed)
    if size <= _RANDBYTES_MAX:
        return rng.randbytes(size)
    parts: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = min(remaining, _RANDBYTES_MAX)
        parts.append(rng.randbytes(chunk))
        remaining -= chunk
    return b"".join(parts)


def empty() -> bytes:
    return b""


def tiny() -> bytes:
    """1 byte: 0x42, per ts-spec-013 §2."""
    return b"\x42"


def exact(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(EXACT_SIZE, seed)


def small(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(SMALL_SIZE, seed)


def medium(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(MEDIUM_SIZE, seed)
