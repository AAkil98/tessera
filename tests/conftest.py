"""Shared pytest fixtures for the Tessera test suite.

All fixtures that produce random data use a deterministic PRNG so that
tests are reproducible across runs and machines.
"""

from __future__ import annotations

import random

import pytest

FIXED_SEED = 42


@pytest.fixture
def prng() -> random.Random:
    """Seeded PRNG — yields the same sequence every run."""
    return random.Random(FIXED_SEED)
