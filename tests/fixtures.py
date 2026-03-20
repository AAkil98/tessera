"""Test data generation helpers.

Provides deterministic byte sequences for standard fixture sizes:
  empty  — 0 bytes
  tiny   — 1 KiB (sub-chunk)
  exact  — 256 KiB (exactly one chunk)
  small  — 768 KiB (three chunks)
  medium — 5 MiB (twenty chunks)
"""
from __future__ import annotations

import random


FIXED_SEED = 42
DEFAULT_CHUNK_SIZE = 256 * 1024  # 256 KiB — matches ts-spec-006

TINY_SIZE = 1024                      # 1 KiB
EXACT_SIZE = DEFAULT_CHUNK_SIZE       # 256 KiB
SMALL_SIZE = DEFAULT_CHUNK_SIZE * 3   # 768 KiB
MEDIUM_SIZE = DEFAULT_CHUNK_SIZE * 20 # 5 MiB
EMPTY_SIZE = 0


def make_bytes(size: int, seed: int = FIXED_SEED) -> bytes:
    """Return *size* deterministic pseudorandom bytes seeded with *seed*."""
    return random.Random(seed).randbytes(size)


def empty() -> bytes:
    return b""


def tiny(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(TINY_SIZE, seed)


def exact(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(EXACT_SIZE, seed)


def small(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(SMALL_SIZE, seed)


def medium(seed: int = FIXED_SEED) -> bytes:
    return make_bytes(MEDIUM_SIZE, seed)
