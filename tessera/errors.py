"""Tessera exception hierarchy.

Spec: ts-spec-010 §5

All public exceptions inherit from TesseraError. Internal components raise
specific subclasses; TesseraNode catches them and re-raises as the public
exceptions listed here.
"""

from __future__ import annotations


class TesseraError(Exception):
    """Base class for all Tessera exceptions."""


class ModerationError(TesseraError):
    """Content moderation rejected the operation.

    Attributes:
        reason: Human-readable explanation from the moderation adapter.
        manifest_hash: The manifest hash involved, if available.
    """

    def __init__(self, reason: str, manifest_hash: bytes | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.manifest_hash = manifest_hash


class CapacityError(TesseraError):
    """Node capacity exhausted.

    Raised when max_swarms_per_node is reached and a new publish() or
    fetch() is attempted.

    Attributes:
        current: Number of active swarms.
        maximum: The configured limit.
    """

    def __init__(self, current: int, maximum: int) -> None:
        super().__init__(
            f"capacity exhausted: {current}/{maximum} swarms active"
        )
        self.current = current
        self.maximum = maximum


class StarvationError(TesseraError):
    """No peers found within the starvation timeout.

    Attributes:
        manifest_hash: The mosaic that could not be fetched.
        elapsed: Seconds spent waiting.
    """

    def __init__(self, manifest_hash: bytes, elapsed: float) -> None:
        super().__init__(
            f"no peers found after {elapsed:.1f}s for "
            f"{manifest_hash[:8].hex()}..."
        )
        self.manifest_hash = manifest_hash
        self.elapsed = elapsed


class IntegrityError(TesseraError):
    """Whole-file verification failed.

    Attributes:
        manifest_hash: The mosaic's manifest hash.
        expected: The file hash declared in the manifest.
        actual: The hash of the assembled file.
    """

    def __init__(
        self, manifest_hash: bytes, expected: bytes, actual: bytes
    ) -> None:
        super().__init__(
            f"whole-file verification failed for "
            f"{manifest_hash[:8].hex()}: "
            f"expected {expected.hex()}, got {actual.hex()}"
        )
        self.manifest_hash = manifest_hash
        self.expected = expected
        self.actual = actual


class ProtocolError(TesseraError):
    """Wire protocol violation.

    Attributes:
        peer_id: The AgentId of the peer that caused the error.
        error_code: The wire protocol error code (ts-spec-005 §7).
    """

    def __init__(
        self,
        peer_id: bytes,
        error_code: int,
        message: str = "",
    ) -> None:
        super().__init__(
            message
            or f"protocol error 0x{error_code:04X} from {peer_id[:8].hex()}..."
        )
        self.peer_id = peer_id
        self.error_code = error_code


class HandshakeError(ProtocolError):
    """Handshake failed or was rejected."""


class MessageError(ProtocolError):
    """Received a malformed or unexpected message."""


class ConfigError(TesseraError):
    """Invalid configuration.

    Attributes:
        field: The config field name.
        reason: Why the value is invalid.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"invalid config field '{field}': {reason}")
        self.field = field
        self.reason = reason
