"""Unit tests for wire message codec and state machine — ts-spec-013 §3.5."""

from __future__ import annotations

import struct

import pytest

from tessera.errors import MessageError
from tessera.wire import errors as werr
from tessera.wire.messages import (
    PROTOCOL_VERSION,
    BitfieldMsg,
    Cancel,
    ExtensionMessage,
    Handshake,
    Have,
    KeepAlive,
    Message,
    Piece,
    Reject,
    Request,
    decode,
    encode,
)
from tessera.wire.state_machine import PeerSession, PeerState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HASH = b"\xab" * 32


def _roundtrip(msg: Message) -> Message:
    return decode(encode(msg))


# ---------------------------------------------------------------------------
# §3.5 — Round-trip tests for all 8 message types
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_roundtrip_handshake() -> None:
    msg = Handshake(
        version=PROTOCOL_VERSION,
        manifest_hash=_HASH,
        tessera_count=100,
        tessera_size=262_144,
    )
    wire = encode(msg)
    assert len(wire) == 43
    result = decode(wire)
    assert isinstance(result, Handshake)
    assert result.version == PROTOCOL_VERSION
    assert result.manifest_hash == _HASH
    assert result.tessera_count == 100
    assert result.tessera_size == 262_144


@pytest.mark.unit
def test_roundtrip_bitfield_sizes() -> None:
    """Bitfield round-trips for N=1, 8, 9, 1000, 4096."""
    for n_bits in (1, 8, 9, 1000, 4096):
        byte_len = (n_bits + 7) // 8
        bf_bytes = bytes(range(byte_len % 256)) * (byte_len // 256 + 1)
        bf_bytes = bf_bytes[:byte_len]
        msg = BitfieldMsg(bitfield_bytes=bf_bytes)
        wire = encode(msg)
        result = decode(wire)
        assert isinstance(result, BitfieldMsg)
        assert result.bitfield_bytes == bf_bytes


@pytest.mark.unit
def test_roundtrip_request() -> None:
    msg = Request(index=42)
    wire = encode(msg)
    assert len(wire) == 5
    result = decode(wire)
    assert isinstance(result, Request)
    assert result.index == 42


@pytest.mark.unit
def test_roundtrip_piece() -> None:
    data = b"\xde\xad\xbe\xef" * 64
    msg = Piece(index=7, data=data)
    wire = encode(msg)
    assert len(wire) == 5 + len(data)
    result = decode(wire)
    assert isinstance(result, Piece)
    assert result.index == 7
    assert result.data == data


@pytest.mark.unit
def test_roundtrip_have() -> None:
    msg = Have(index=999)
    wire = encode(msg)
    assert len(wire) == 5
    result = decode(wire)
    assert isinstance(result, Have)
    assert result.index == 999


@pytest.mark.unit
def test_roundtrip_cancel() -> None:
    msg = Cancel(index=500)
    wire = encode(msg)
    assert len(wire) == 5
    result = decode(wire)
    assert isinstance(result, Cancel)
    assert result.index == 500


@pytest.mark.unit
def test_roundtrip_reject() -> None:
    msg = Reject(
        rejected_type=0x04,
        error_code=werr.HASH_MISMATCH,
        context=107,
    )
    wire = encode(msg)
    assert len(wire) == 8
    result = decode(wire)
    assert isinstance(result, Reject)
    assert result.rejected_type == 0x04
    assert result.error_code == werr.HASH_MISMATCH
    assert result.context == 107


@pytest.mark.unit
def test_roundtrip_reject_zero_context() -> None:
    msg = Reject(rejected_type=0x01, error_code=werr.UNEXPECTED_MSG)
    wire = encode(msg)
    result = decode(wire)
    assert isinstance(result, Reject)
    assert result.context == 0


@pytest.mark.unit
def test_roundtrip_keepalive() -> None:
    msg = KeepAlive()
    wire = encode(msg)
    assert wire == b"\x08"
    result = decode(wire)
    assert isinstance(result, KeepAlive)


# ---------------------------------------------------------------------------
# Unknown / extension type handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_decode_unknown_core_type() -> None:
    """msg_type 0x09 (reserved core) → MessageError UNKNOWN_MSG_TYPE."""
    with pytest.raises(MessageError) as exc_info:
        decode(b"\x09\x00\x00")
    assert exc_info.value.error_code == werr.UNKNOWN_MSG_TYPE


@pytest.mark.unit
def test_decode_reserved_zero() -> None:
    """msg_type 0x00 → MessageError UNKNOWN_MSG_TYPE."""
    with pytest.raises(MessageError) as exc_info:
        decode(b"\x00")
    assert exc_info.value.error_code == werr.UNKNOWN_MSG_TYPE


@pytest.mark.unit
def test_decode_extension_type_ignored() -> None:
    """msg_type 0x80 → ExtensionMessage, no error."""
    result = decode(b"\x80\xca\xfe")
    assert isinstance(result, ExtensionMessage)
    assert result.msg_type == 0x80
    assert result.body == b"\xca\xfe"


@pytest.mark.unit
def test_decode_extension_type_max() -> None:
    result = decode(b"\xff")
    assert isinstance(result, ExtensionMessage)
    assert result.msg_type == 0xFF


# ---------------------------------------------------------------------------
# Truncation / malformed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_decode_truncated_handshake() -> None:
    """10-byte HANDSHAKE → MessageError MALFORMED_MSG."""
    wire = b"\x01" + b"\x00" * 9  # only 10 bytes, needs 43
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_decode_truncated_request() -> None:
    wire = b"\x03\x00\x00"  # only 3 bytes, needs 5
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_decode_truncated_reject() -> None:
    wire = b"\x07\x04\x02"  # only 3 bytes, needs 8
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_decode_empty() -> None:
    with pytest.raises(MessageError) as exc_info:
        decode(b"")
    assert exc_info.value.error_code == werr.MALFORMED_MSG


# ---------------------------------------------------------------------------
# Big-endian encoding
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_big_endian_request() -> None:
    """REQUEST index=0x00000100 must be b'\\x03\\x00\\x00\\x01\\x00'."""
    wire = encode(Request(index=0x00000100))
    assert wire == b"\x03\x00\x00\x01\x00"


@pytest.mark.unit
def test_big_endian_handshake() -> None:
    """tessera_count=0x00000001 must appear as 4 big-endian bytes."""
    msg = Handshake(
        version=1,
        manifest_hash=b"\x00" * 32,
        tessera_count=1,
        tessera_size=262_144,
    )
    wire = encode(msg)
    # tessera_count starts at offset 1+2+32 = 35
    (tc,) = struct.unpack_from("!I", wire, 35)
    assert tc == 1
    assert wire[35:39] == b"\x00\x00\x00\x01"


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_state_machine_happy_path() -> None:
    """HANDSHAKE → BITFIELD → TRANSFER is the only valid receive sequence."""
    session = PeerSession()
    assert session.state == PeerState.AWAITING_HANDSHAKE

    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    assert session.state == PeerState.AWAITING_BITFIELD

    session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    assert session.state == PeerState.TRANSFER

    # Transfer-phase messages accepted.
    session.on_receive(Request(index=0))
    session.on_receive(Piece(index=0, data=b"x"))
    session.on_receive(Have(index=0))
    session.on_receive(Cancel(index=0))
    session.on_receive(KeepAlive())


@pytest.mark.unit
def test_request_before_handshake() -> None:
    """REQUEST as first message → UNEXPECTED_MSG."""
    session = PeerSession()
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Request(index=0))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_request_before_bitfield() -> None:
    """HANDSHAKE then REQUEST (skipping BITFIELD) → UNEXPECTED_MSG."""
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Request(index=0))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_duplicate_handshake() -> None:
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Handshake(1, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_duplicate_bitfield() -> None:
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_handshake_in_transfer_state() -> None:
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Handshake(1, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_send_handshake_once() -> None:
    session = PeerSession()
    session.on_send(Handshake(1, _HASH, 4, 262_144))
    with pytest.raises(MessageError) as exc_info:
        session.on_send(Handshake(1, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_send_bitfield_before_handshake() -> None:
    session = PeerSession()
    with pytest.raises(MessageError) as exc_info:
        session.on_send(BitfieldMsg(bitfield_bytes=b"\x00"))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_send_request_before_bitfield() -> None:
    session = PeerSession()
    session.on_send(Handshake(1, _HASH, 4, 262_144))
    with pytest.raises(MessageError) as exc_info:
        session.on_send(Request(index=0))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_extension_type_valid_in_transfer() -> None:
    """Extension messages are accepted in TRANSFER without error."""
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    session.on_receive(ExtensionMessage(msg_type=0x80, body=b"data"))


@pytest.mark.unit
def test_closed_session_rejects_all() -> None:
    session = PeerSession()
    session.close()
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Handshake(1, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG
