"""Adversarial tests: transfer / wire protocol errors -- ts-spec-013 section 6.4.

Protocol-level wire error scenarios exercising the PeerSession state machine
and message encode/decode. These complement the unit tests in
tests/unit/test_messages.py by focusing on adversarial error paths.
"""

from __future__ import annotations

import pytest

from tessera.errors import MessageError
from tessera.wire import errors as werr
from tessera.wire.messages import (
    PROTOCOL_VERSION,
    Handshake,
    Reject,
    Request,
    decode,
    encode,
)
from tessera.wire.state_machine import PeerSession, PeerState

_HASH = b"\xab" * 32


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
async def test_request_before_handshake() -> None:
    """PeerSession receives a Request before any Handshake.

    ts-spec-005 section 3: the first message on a fresh session MUST be a
    Handshake. A Request arriving first is an UNEXPECTED_MSG violation.
    The session must remain in AWAITING_HANDSHAKE after the rejection.
    """
    session = PeerSession(peer_id=b"\x01" * 8)
    assert session.state == PeerState.AWAITING_HANDSHAKE

    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Request(index=0))

    assert exc_info.value.error_code == werr.UNEXPECTED_MSG
    # Session state must not advance.
    assert session.state == PeerState.AWAITING_HANDSHAKE


@pytest.mark.adversarial
async def test_duplicate_handshake() -> None:
    """PeerSession receives two Handshakes in succession.

    ts-spec-005 section 3: a second Handshake is a DUPLICATE_MSG violation.
    After receiving the first valid Handshake the session advances to
    AWAITING_BITFIELD. The duplicate must be rejected without changing state.
    """
    session = PeerSession(peer_id=b"\x02" * 8)
    hs = Handshake(
        version=PROTOCOL_VERSION,
        manifest_hash=_HASH,
        tessera_count=4,
        tessera_size=262_144,
    )

    session.on_receive(hs)
    assert session.state == PeerState.AWAITING_BITFIELD

    with pytest.raises(MessageError) as exc_info:
        session.on_receive(hs)

    assert exc_info.value.error_code == werr.DUPLICATE_MSG
    # State must remain AWAITING_BITFIELD (not regress or advance).
    assert session.state == PeerState.AWAITING_BITFIELD


@pytest.mark.adversarial
async def test_reject_message_decodes() -> None:
    """Build a Reject message with known fields; encode/decode round-trips cleanly.

    Verifies that adversarial Reject messages with various error codes can
    be serialized and deserialized without data loss, which is critical for
    correctly propagating error information between peers.
    """
    original = Reject(
        rejected_type=0x03,  # REQUEST
        error_code=werr.INDEX_OUT_OF_RANGE,
        context=42,
    )

    wire = encode(original)
    restored = decode(wire)

    assert isinstance(restored, Reject)
    assert restored.rejected_type == original.rejected_type
    assert restored.error_code == original.error_code
    assert restored.context == original.context

    # Also verify a Reject with a capacity error code.
    overload = Reject(
        rejected_type=0x03,
        error_code=werr.OVERLOADED,
        context=0,
    )
    wire2 = encode(overload)
    restored2 = decode(wire2)

    assert isinstance(restored2, Reject)
    assert restored2.error_code == werr.OVERLOADED
    assert restored2.context == 0


@pytest.mark.adversarial
async def test_request_before_bitfield_in_awaiting_bitfield() -> None:
    """After Handshake, a Request (skipping Bitfield) is rejected.

    The state machine should enforce the full ordering:
    HANDSHAKE -> BITFIELD -> transfer messages.
    """
    session = PeerSession(peer_id=b"\x03" * 8)
    session.on_receive(
        Handshake(
            version=PROTOCOL_VERSION,
            manifest_hash=_HASH,
            tessera_count=4,
            tessera_size=262_144,
        )
    )
    assert session.state == PeerState.AWAITING_BITFIELD

    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Request(index=5))

    assert exc_info.value.error_code == werr.UNEXPECTED_MSG
    assert session.state == PeerState.AWAITING_BITFIELD


@pytest.mark.adversarial
async def test_closed_session_rejects_send_and_receive() -> None:
    """A closed session rejects both incoming and outgoing messages.

    After close(), no further protocol interaction is allowed.
    """
    session = PeerSession(peer_id=b"\x04" * 8)
    session.close()
    assert session.state == PeerState.CLOSED

    with pytest.raises(MessageError) as exc_info:
        session.on_receive(Handshake(PROTOCOL_VERSION, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG

    with pytest.raises(MessageError) as exc_info:
        session.on_send(Handshake(PROTOCOL_VERSION, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG
