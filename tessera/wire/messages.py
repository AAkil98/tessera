"""Tessera wire message types and binary codec.

Spec: ts-spec-005 §3–4

All messages are big-endian. Each starts with a 1-byte msg_type tag.
The ``encode`` / ``decode`` functions are the only public entry points
for serialization — callers never build raw bytes by hand.

Extension messages (0x80–0xFF) are returned as ``ExtensionMessage`` so
the state machine can silently ignore them without raising.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import ClassVar

from tessera.errors import MessageError
from tessera.wire import errors as werr

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: int = 0x0001

# msg_type byte values
_TYPE_HANDSHAKE: int = 0x01
_TYPE_BITFIELD: int = 0x02
_TYPE_REQUEST: int = 0x03
_TYPE_PIECE: int = 0x04
_TYPE_HAVE: int = 0x05
_TYPE_CANCEL: int = 0x06
_TYPE_REJECT: int = 0x07
_TYPE_KEEP_ALIVE: int = 0x08

# Struct formats (big-endian, body only — msg_type byte already consumed)
_FMT_HANDSHAKE: str = (
    "!H32sII"  # version(2) + manifest_hash(32) + tessera_count(4) + tessera_size(4)
)
_FMT_INDEX: str = "!I"  # single u32 index
_FMT_REJECT: str = "!BHI"  # rejected_type(1) + error_code(2) + context(4)

_SIZE_HANDSHAKE_BODY: int = struct.calcsize(_FMT_HANDSHAKE)  # 42
_SIZE_HANDSHAKE: int = 1 + _SIZE_HANDSHAKE_BODY  # 43
_SIZE_INDEX_MSG: int = 5  # msg_type(1) + index(4)
_SIZE_REJECT: int = 8  # msg_type(1) + rejected_type(1) + error_code(2) + context(4)


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Handshake:
    """HANDSHAKE (0x01) — initiate a peer session."""

    MSG_TYPE: ClassVar[int] = _TYPE_HANDSHAKE

    version: int
    manifest_hash: bytes  # 32 bytes
    tessera_count: int
    tessera_size: int


@dataclass
class BitfieldMsg:
    """BITFIELD (0x02) — declare which tesserae the sender holds.

    ``bitfield_bytes`` is ⌈tessera_count / 8⌉ raw bytes, MSB-first,
    trailing bits zero-padded.  Use ``tessera.content.bitfield.Bitfield``
    for bit-level operations.
    """

    MSG_TYPE: ClassVar[int] = _TYPE_BITFIELD

    bitfield_bytes: bytes


@dataclass
class Request:
    """REQUEST (0x03) — ask the peer for one tessera."""

    MSG_TYPE: ClassVar[int] = _TYPE_REQUEST

    index: int


@dataclass
class Piece:
    """PIECE (0x04) — deliver one tessera payload."""

    MSG_TYPE: ClassVar[int] = _TYPE_PIECE

    index: int
    data: bytes


@dataclass
class Have:
    """HAVE (0x05) — announce a newly acquired tessera."""

    MSG_TYPE: ClassVar[int] = _TYPE_HAVE

    index: int


@dataclass
class Cancel:
    """CANCEL (0x06) — withdraw a previously sent REQUEST."""

    MSG_TYPE: ClassVar[int] = _TYPE_CANCEL

    index: int


@dataclass
class Reject:
    """REJECT (0x07) — refuse a message with an error code."""

    MSG_TYPE: ClassVar[int] = _TYPE_REJECT

    rejected_type: int
    error_code: int
    context: int = 0


@dataclass
class KeepAlive:
    """KEEP_ALIVE (0x08) — heartbeat, no body."""

    MSG_TYPE: ClassVar[int] = _TYPE_KEEP_ALIVE


@dataclass
class ExtensionMessage:
    """Unrecognized extension message (0x80–0xFF).

    The receiver silently ignores these per ts-spec-005 §8.
    """

    msg_type: int
    body: bytes = field(default_factory=bytes)


# Union of all message types that ``decode`` may return.
Message = (
    Handshake
    | BitfieldMsg
    | Request
    | Piece
    | Have
    | Cancel
    | Reject
    | KeepAlive
    | ExtensionMessage
)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def encode(msg: Message) -> bytes:
    """Serialize *msg* to wire bytes (big-endian, msg_type prefix included)."""
    if isinstance(msg, Handshake):
        return bytes([_TYPE_HANDSHAKE]) + struct.pack(
            _FMT_HANDSHAKE,
            msg.version,
            msg.manifest_hash,
            msg.tessera_count,
            msg.tessera_size,
        )
    if isinstance(msg, BitfieldMsg):
        return bytes([_TYPE_BITFIELD]) + msg.bitfield_bytes
    if isinstance(msg, Request):
        return bytes([_TYPE_REQUEST]) + struct.pack(_FMT_INDEX, msg.index)
    if isinstance(msg, Piece):
        return bytes([_TYPE_PIECE]) + struct.pack(_FMT_INDEX, msg.index) + msg.data
    if isinstance(msg, Have):
        return bytes([_TYPE_HAVE]) + struct.pack(_FMT_INDEX, msg.index)
    if isinstance(msg, Cancel):
        return bytes([_TYPE_CANCEL]) + struct.pack(_FMT_INDEX, msg.index)
    if isinstance(msg, Reject):
        return bytes([_TYPE_REJECT]) + struct.pack(
            _FMT_REJECT,
            msg.rejected_type,
            msg.error_code,
            msg.context,
        )
    if isinstance(msg, KeepAlive):
        return bytes([_TYPE_KEEP_ALIVE])
    if isinstance(msg, ExtensionMessage):
        return bytes([msg.msg_type]) + msg.body
    raise TypeError(f"cannot encode unknown message type: {type(msg)!r}")


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def decode(data: bytes) -> Message:
    """Deserialize *data* into a ``Message``.

    Args:
        data: Raw bytes starting with the msg_type byte.

    Returns:
        A message dataclass, or ``ExtensionMessage`` for 0x80–0xFF types.

    Raises:
        MessageError: MALFORMED_MSG if truncated or structurally invalid.
        MessageError: UNKNOWN_MSG_TYPE for reserved / unknown core types.
    """
    if not data:
        raise MessageError(b"", werr.MALFORMED_MSG, "empty message")

    msg_type = data[0]

    if msg_type == _TYPE_HANDSHAKE:
        if len(data) < _SIZE_HANDSHAKE:
            _malformed(f"HANDSHAKE too short: {len(data)} < {_SIZE_HANDSHAKE}")
        version, manifest_hash, tessera_count, tessera_size = struct.unpack_from(
            _FMT_HANDSHAKE, data, 1
        )
        return Handshake(
            version=version,
            manifest_hash=manifest_hash,
            tessera_count=tessera_count,
            tessera_size=tessera_size,
        )

    if msg_type == _TYPE_BITFIELD:
        return BitfieldMsg(bitfield_bytes=data[1:])

    if msg_type == _TYPE_REQUEST:
        if len(data) < _SIZE_INDEX_MSG:
            _malformed(f"REQUEST too short: {len(data)}")
        (index,) = struct.unpack_from(_FMT_INDEX, data, 1)
        return Request(index=index)

    if msg_type == _TYPE_PIECE:
        if len(data) < _SIZE_INDEX_MSG:
            _malformed(f"PIECE too short: {len(data)}")
        (index,) = struct.unpack_from(_FMT_INDEX, data, 1)
        return Piece(index=index, data=data[5:])

    if msg_type == _TYPE_HAVE:
        if len(data) < _SIZE_INDEX_MSG:
            _malformed(f"HAVE too short: {len(data)}")
        (index,) = struct.unpack_from(_FMT_INDEX, data, 1)
        return Have(index=index)

    if msg_type == _TYPE_CANCEL:
        if len(data) < _SIZE_INDEX_MSG:
            _malformed(f"CANCEL too short: {len(data)}")
        (index,) = struct.unpack_from(_FMT_INDEX, data, 1)
        return Cancel(index=index)

    if msg_type == _TYPE_REJECT:
        if len(data) < _SIZE_REJECT:
            _malformed(f"REJECT too short: {len(data)}")
        rejected_type, error_code, context = struct.unpack_from(_FMT_REJECT, data, 1)
        return Reject(
            rejected_type=rejected_type,
            error_code=error_code,
            context=context,
        )

    if msg_type == _TYPE_KEEP_ALIVE:
        return KeepAlive()

    if 0x80 <= msg_type <= 0xFF:
        # Extension range — silently ignore per ts-spec-005 §8.
        return ExtensionMessage(msg_type=msg_type, body=data[1:])

    # Reserved (0x00) or future core types (0x09–0x7F).
    raise MessageError(
        b"",
        werr.UNKNOWN_MSG_TYPE,
        f"unknown message type 0x{msg_type:02X}",
    )


def _malformed(detail: str) -> None:
    """Raise MessageError(MALFORMED_MSG) with *detail*."""
    raise MessageError(b"", werr.MALFORMED_MSG, detail)
