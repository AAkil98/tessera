"""Peer session state machine.

Spec: ts-spec-005 §3

State transitions on the *receive* side:

  AWAITING_HANDSHAKE  →(HANDSHAKE received)→  AWAITING_BITFIELD
  AWAITING_BITFIELD   →(BITFIELD received)→   TRANSFER
  TRANSFER            →                        TRANSFER  (all transfer msgs)

Any message arriving out of sequence raises MessageError or HandshakeError.
"""

from __future__ import annotations

from enum import Enum

from tessera.errors import MessageError
from tessera.wire import errors as werr
from tessera.wire.messages import (
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
)

# Transfer-phase message types — valid after both HANDSHAKE and BITFIELD.
_TRANSFER_TYPES = (Request, Piece, Have, Cancel, Reject, KeepAlive, ExtensionMessage)


class PeerState(Enum):
    """States on the *receive* side of a peer session."""

    AWAITING_HANDSHAKE = "AWAITING_HANDSHAKE"
    """No HANDSHAKE received yet. Only HANDSHAKE is valid."""

    AWAITING_BITFIELD = "AWAITING_BITFIELD"
    """HANDSHAKE received. Waiting for BITFIELD before transfer can begin."""

    TRANSFER = "TRANSFER"
    """Both HANDSHAKE and BITFIELD received. Full transfer phase active."""

    CLOSED = "CLOSED"
    """Session closed. No further messages are accepted."""


class PeerSession:
    """Per-channel state machine enforcing ts-spec-005 §3 message ordering.

    Tracks the receive sequence for one remote peer on one channel.
    Call ``on_receive`` for every decoded message to validate ordering.
    Call ``on_send`` before emitting a message to validate our own sequence.

    The session is intentionally not thread-safe — callers serialize access.
    """

    def __init__(self, peer_id: bytes = b"") -> None:
        self._peer_id = peer_id
        self._recv_state = PeerState.AWAITING_HANDSHAKE
        self._sent_handshake = False
        self._sent_bitfield = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> PeerState:
        """Current receive-side state."""
        return self._recv_state

    @property
    def peer_id(self) -> bytes:
        return self._peer_id

    def set_peer_id(self, peer_id: bytes) -> None:
        """Set the peer's AgentId once known (after HANDSHAKE)."""
        self._peer_id = peer_id

    def on_receive(self, msg: Message) -> None:
        """Validate that *msg* is legal in the current receive state.

        Raises:
            MessageError: UNEXPECTED_MSG — message invalid in current state.
            MessageError: DUPLICATE_MSG  — HANDSHAKE or BITFIELD sent twice.
            HandshakeError: MANIFEST_MISMATCH / VERSION_MISMATCH — checked
                            externally; this method only validates ordering.
        """
        if self._recv_state == PeerState.CLOSED:
            raise MessageError(
                self._peer_id,
                werr.UNEXPECTED_MSG,
                "message received on a closed session",
            )

        if self._recv_state == PeerState.AWAITING_HANDSHAKE:
            if not isinstance(msg, Handshake):
                raise MessageError(
                    self._peer_id,
                    werr.UNEXPECTED_MSG,
                    f"expected HANDSHAKE as first message, got {type(msg).__name__}",
                )
            self._recv_state = PeerState.AWAITING_BITFIELD
            return

        if self._recv_state == PeerState.AWAITING_BITFIELD:
            if isinstance(msg, Handshake):
                raise MessageError(
                    self._peer_id,
                    werr.DUPLICATE_MSG,
                    "duplicate HANDSHAKE",
                )
            if not isinstance(msg, BitfieldMsg):
                raise MessageError(
                    self._peer_id,
                    werr.UNEXPECTED_MSG,
                    f"expected BITFIELD after HANDSHAKE, got {type(msg).__name__}",
                )
            self._recv_state = PeerState.TRANSFER
            return

        # TRANSFER state
        if isinstance(msg, Handshake):
            raise MessageError(
                self._peer_id,
                werr.DUPLICATE_MSG,
                "second HANDSHAKE in TRANSFER state",
            )
        if isinstance(msg, BitfieldMsg):
            raise MessageError(
                self._peer_id,
                werr.DUPLICATE_MSG,
                "second BITFIELD in TRANSFER state",
            )
        # All other message types are valid in TRANSFER.

    def on_send(self, msg: Message) -> None:
        """Validate that we are allowed to send *msg* right now.

        Raises:
            MessageError: If sending would violate the protocol.
        """
        if self._recv_state == PeerState.CLOSED:
            raise MessageError(
                self._peer_id,
                werr.UNEXPECTED_MSG,
                "cannot send on a closed session",
            )

        if isinstance(msg, Handshake):
            if self._sent_handshake:
                raise MessageError(
                    self._peer_id,
                    werr.DUPLICATE_MSG,
                    "attempted to send a second HANDSHAKE",
                )
            self._sent_handshake = True
            return

        if isinstance(msg, BitfieldMsg):
            if not self._sent_handshake:
                raise MessageError(
                    self._peer_id,
                    werr.UNEXPECTED_MSG,
                    "cannot send BITFIELD before HANDSHAKE",
                )
            if self._sent_bitfield:
                raise MessageError(
                    self._peer_id,
                    werr.DUPLICATE_MSG,
                    "attempted to send a second BITFIELD",
                )
            self._sent_bitfield = True
            return

        # Transfer-phase messages require both HANDSHAKE and BITFIELD sent.
        if not (self._sent_handshake and self._sent_bitfield):
            raise MessageError(
                self._peer_id,
                werr.UNEXPECTED_MSG,
                f"cannot send {type(msg).__name__} before handshake/bitfield exchange",
            )

    def close(self) -> None:
        """Mark the session as closed. No further messages are accepted."""
        self._recv_state = PeerState.CLOSED
