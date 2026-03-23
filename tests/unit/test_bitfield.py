"""Unit tests for Bitfield — ts-spec-013 §3.7."""

from __future__ import annotations

import pytest

from tessera.content.bitfield import Bitfield


@pytest.mark.unit
def test_bitfield_set_get() -> None:
    bf = Bitfield(100)
    bf.set(42)
    assert bf.get(42) is True
    assert bf.get(41) is False
    assert bf.get(43) is False


@pytest.mark.unit
def test_bitfield_count() -> None:
    bf = Bitfield(100)
    for i in (0, 5, 99):
        bf.set(i)
    assert bf.count_set() == 3


@pytest.mark.unit
def test_bitfield_all_set() -> None:
    bf = Bitfield(8)
    assert bf.is_complete() is False
    for i in range(8):
        bf.set(i)
    assert bf.is_complete() is True


@pytest.mark.unit
def test_bitfield_all_set_non_multiple() -> None:
    """count=10 — last 6 trailing bits in byte 1 must stay zero."""
    bf = Bitfield(10)
    for i in range(10):
        bf.set(i)
    assert bf.is_complete() is True
    assert bf.count_set() == 10


@pytest.mark.unit
def test_bitfield_serialization_roundtrip() -> None:
    bf = Bitfield(100)
    for i in (0, 7, 8, 63, 99):
        bf.set(i)
    restored = Bitfield.from_bytes(100, bf.to_bytes())
    assert restored == bf
    for i in range(100):
        assert restored.get(i) == bf.get(i)


@pytest.mark.unit
def test_bitfield_msb_first() -> None:
    """Bit 0 is the MSB of byte 0; bit 7 is the LSB of byte 0."""
    bf = Bitfield(8)
    bf.set(0)
    assert bf.to_bytes() == b"\x80"

    bf2 = Bitfield(8)
    bf2.set(7)
    assert bf2.to_bytes() == b"\x01"


@pytest.mark.unit
def test_bitfield_trailing_padding() -> None:
    """N=10 → 2 serialized bytes; bits 10–15 are zero."""
    bf = Bitfield(10)
    assert len(bf.to_bytes()) == 2
    # Set all valid bits and verify trailing bits are still zero.
    for i in range(10):
        bf.set(i)
    raw = bf.to_bytes()
    # Second byte: bits 8 and 9 are the top two bits (0xC0), rest zero.
    assert raw[1] & 0x3F == 0  # lower 6 bits of byte 1 must be 0


@pytest.mark.unit
def test_bitfield_base64_roundtrip() -> None:
    bf = Bitfield(100)
    for i in (1, 50, 99):
        bf.set(i)
    restored = Bitfield.from_base64(100, bf.to_base64())
    assert restored == bf


@pytest.mark.unit
def test_bitfield_clear() -> None:
    bf = Bitfield(16)
    bf.set(5)
    assert bf.get(5) is True
    bf.clear(5)
    assert bf.get(5) is False
    assert bf.count_set() == 0


@pytest.mark.unit
def test_bitfield_index_out_of_range() -> None:
    bf = Bitfield(10)
    with pytest.raises(IndexError):
        bf.get(10)
    with pytest.raises(IndexError):
        bf.set(-1)


@pytest.mark.unit
def test_bitfield_zero_count() -> None:
    bf = Bitfield(0)
    assert bf.to_bytes() == b""
    assert bf.is_complete() is True
    assert bf.count_set() == 0


@pytest.mark.unit
def test_bitfield_wrong_data_length() -> None:
    with pytest.raises(ValueError):
        Bitfield(8, b"\x00\x00")  # 8 bits needs 1 byte, not 2


@pytest.mark.unit
def test_bitfield_equality() -> None:
    a = Bitfield(16)
    b = Bitfield(16)
    a.set(3)
    b.set(3)
    assert a == b
    b.set(4)
    assert a != b
