"""Unit tests for Merkle tree — ts-spec-013 §3.2."""

from __future__ import annotations

import hashlib

import pytest

from tessera.content.merkle import build_root, _EMPTY_ROOT


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _leaves(n: int) -> list[bytes]:
    """Generate n distinct deterministic 32-byte leaf hashes."""
    return [_h(i.to_bytes(4, "big")) for i in range(n)]


@pytest.mark.unit
def test_merkle_empty() -> None:
    """0 leaves → 32 zero bytes."""
    assert build_root([]) == _EMPTY_ROOT
    assert build_root([]) == b"\x00" * 32


@pytest.mark.unit
def test_merkle_single_leaf() -> None:
    """1 leaf → root == that leaf (no internal nodes)."""
    leaf = _h(b"only")
    assert build_root([leaf]) == leaf


@pytest.mark.unit
def test_merkle_two_leaves() -> None:
    """2 leaves → SHA-256(leaf[0] || leaf[1])."""
    leaves = _leaves(2)
    expected = _h(leaves[0] + leaves[1])
    assert build_root(leaves) == expected


@pytest.mark.unit
def test_merkle_power_of_two() -> None:
    """4 leaves → balanced tree."""
    L = _leaves(4)
    # Level 1
    h01 = _h(L[0] + L[1])
    h23 = _h(L[2] + L[3])
    # Level 2 (root)
    root = _h(h01 + h23)
    assert build_root(L) == root


@pytest.mark.unit
def test_merkle_odd_promotion_3() -> None:
    """3 leaves: L[2] promoted at level 1."""
    L = _leaves(3)
    h01 = _h(L[0] + L[1])
    # L[2] promoted — not hashed with itself
    root = _h(h01 + L[2])
    assert build_root(L) == root


@pytest.mark.unit
def test_merkle_odd_promotion_5() -> None:
    """5 leaves — matches spec example exactly."""
    L = _leaves(5)
    # Level 1
    h01 = _h(L[0] + L[1])
    h23 = _h(L[2] + L[3])
    # L[4] promoted to level 1
    # Level 2
    h0123 = _h(h01 + h23)
    # L[4] promoted again to level 2
    # Level 3 (root)
    root = _h(h0123 + L[4])
    assert build_root(L) == root


@pytest.mark.unit
def test_merkle_no_duplication() -> None:
    """Promotion ≠ duplication: wrong (duplicate) tree produces different root."""
    L = _leaves(5)
    # Build the correct (promotion) root
    correct = build_root(L)

    # Simulate wrong duplication: last leaf doubled
    L_dup = L + [L[-1]]  # 6 leaves — even, no promotion
    wrong = build_root(L_dup)

    assert correct != wrong


@pytest.mark.unit
def test_merkle_large() -> None:
    """4,000 leaves — result is deterministic and non-trivial."""
    leaves = _leaves(4000)
    root1 = build_root(leaves)
    root2 = build_root(leaves)
    assert root1 == root2
    assert root1 != _EMPTY_ROOT
    assert len(root1) == 32


@pytest.mark.unit
def test_merkle_different_leaves_different_root() -> None:
    """Changing a single leaf changes the root."""
    leaves = _leaves(8)
    root_original = build_root(leaves)
    leaves[3] = _h(b"tampered")
    root_tampered = build_root(leaves)
    assert root_original != root_tampered
