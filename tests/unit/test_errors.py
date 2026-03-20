"""Unit tests for exception hierarchy — ts-spec-013 §3.9."""

from __future__ import annotations

import pytest

from tessera.errors import (
    CapacityError,
    ConfigError,
    HandshakeError,
    IntegrityError,
    MessageError,
    ModerationError,
    ProtocolError,
    StarvationError,
    TesseraError,
)


@pytest.mark.unit
def test_all_inherit_from_tessera_error() -> None:
    for cls in (
        ModerationError,
        CapacityError,
        StarvationError,
        IntegrityError,
        ProtocolError,
        ConfigError,
    ):
        assert issubclass(cls, TesseraError)


@pytest.mark.unit
def test_protocol_error_subclasses() -> None:
    assert issubclass(HandshakeError, ProtocolError)
    assert issubclass(MessageError, ProtocolError)


@pytest.mark.unit
def test_moderation_error_fields() -> None:
    err = ModerationError("policy violation", manifest_hash=b"\xab" * 32)
    assert err.reason == "policy violation"
    assert err.manifest_hash == b"\xab" * 32


@pytest.mark.unit
def test_moderation_error_no_hash() -> None:
    err = ModerationError("bad content")
    assert err.manifest_hash is None


@pytest.mark.unit
def test_capacity_error_fields() -> None:
    err = CapacityError(current=10, maximum=10)
    assert err.current == 10
    assert err.maximum == 10


@pytest.mark.unit
def test_starvation_error_fields() -> None:
    h = b"\x00" * 32
    err = StarvationError(manifest_hash=h, elapsed=90.5)
    assert err.manifest_hash == h
    assert err.elapsed == pytest.approx(90.5)


@pytest.mark.unit
def test_integrity_error_fields() -> None:
    mh = b"\x01" * 32
    exp = b"\x02" * 32
    act = b"\x03" * 32
    err = IntegrityError(manifest_hash=mh, expected=exp, actual=act)
    assert err.manifest_hash == mh
    assert err.expected == exp
    assert err.actual == act


@pytest.mark.unit
def test_config_error_fields() -> None:
    err = ConfigError("tessera_size", "must be positive")
    assert err.field == "tessera_size"
    assert err.reason == "must be positive"


@pytest.mark.unit
def test_catch_base_class() -> None:
    for exc in (
        ModerationError("x"),
        CapacityError(1, 2),
        StarvationError(b"\x00" * 32, 1.0),
        IntegrityError(b"\x00" * 32, b"\x01" * 32, b"\x02" * 32),
        ProtocolError(b"\x00" * 8, 0x0100),
        ConfigError("f", "r"),
    ):
        with pytest.raises(TesseraError):
            raise exc


@pytest.mark.unit
def test_string_representation() -> None:
    """All exceptions produce non-empty str() output including field info."""
    err = ConfigError("tessera_size", "must be positive")
    assert "tessera_size" in str(err)
    assert "positive" in str(err)

    err2 = CapacityError(8, 10)
    assert "8" in str(err2) and "10" in str(err2)
