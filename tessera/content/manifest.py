"""ManifestBuilder and ManifestParser — binary manifest format.

Spec: ts-spec-006 §4–5

Binary layout (big-endian):
  Offset  Size            Field
  ------  ----            -----
  0       4               magic          b'TSRA'  (0x54535241)
  4       2               format_version 0x0001
  6       32              root_hash      Merkle root (SHA-256)
  38      4               tessera_count  u32
  42      4               tessera_size   u32
  46      8               file_size      u64
  54      4               last_tessera_size u32
  58      2               metadata_len   u16
  60      metadata_len    metadata       length-prefixed key-value pairs
  60+M    32 × N          leaf_hashes    SHA-256 per tessera

Total: 60 + M + 32*N bytes.

Metadata entries (sorted by key):
  1 byte    key_len
  key_len   key    (UTF-8)
  2 bytes   val_len (u16, big-endian)
  val_len   value  (UTF-8)
"""

from __future__ import annotations

import hashlib
import struct

from tessera.content.merkle import build_root
from tessera.errors import ConfigError
from tessera.types import ManifestInfo

MAGIC: bytes = b"TSRA"
FORMAT_VERSION: int = 0x0001

# struct format for the fixed 60-byte header (big-endian)
_HEADER_FMT: str = "!4sH32sIIQIH"
_HEADER_SIZE: int = struct.calcsize(_HEADER_FMT)  # == 60

_MAX_METADATA_LEN: int = 65_535  # u16 max


class ManifestBuilder:
    """Assembles and serializes a manifest from chunked tessera data.

    Usage::

        builder = ManifestBuilder(
            file_size=1_048_576,
            tessera_size=262_144,
            metadata={"name": "file.bin"},
        )
        for index, data, leaf_hash in chunker.chunk(path):
            builder.add_tessera(leaf_hash)
        manifest_bytes = builder.build()
    """

    def __init__(
        self,
        file_size: int,
        tessera_size: int,
        metadata: dict[str, str] | None = None,
        max_metadata_keys: int = 64,
        max_metadata_value_bytes: int = 1024,
    ) -> None:
        self._file_size = file_size
        self._tessera_size = tessera_size
        self._leaf_hashes: list[bytes] = []
        self._max_metadata_keys = max_metadata_keys
        self._max_metadata_value_bytes = max_metadata_value_bytes

        meta = metadata or {}
        self._validate_metadata(meta)
        # Sort keys for deterministic serialization.
        self._metadata: dict[str, str] = dict(sorted(meta.items()))

    def add_tessera(self, leaf_hash: bytes) -> None:
        """Append a tessera's 32-byte SHA-256 leaf hash."""
        if len(leaf_hash) != 32:
            raise ValueError(f"leaf_hash must be 32 bytes, got {len(leaf_hash)}")
        self._leaf_hashes.append(leaf_hash)

    def build(self) -> bytes:
        """Serialize and return the complete manifest bytes."""
        tessera_count = len(self._leaf_hashes)

        if tessera_count == 0:
            last_tessera_size = 0
        elif tessera_count == 1:
            last_tessera_size = self._file_size
        else:
            remainder = self._file_size % self._tessera_size
            last_tessera_size = remainder if remainder != 0 else self._tessera_size

        root_hash = build_root(self._leaf_hashes)
        metadata_bytes = _encode_metadata(self._metadata)

        if len(metadata_bytes) > _MAX_METADATA_LEN:
            raise ConfigError(
                "metadata",
                f"serialized metadata ({len(metadata_bytes)} bytes) "
                f"exceeds {_MAX_METADATA_LEN}",
            )

        header = struct.pack(
            _HEADER_FMT,
            MAGIC,
            FORMAT_VERSION,
            root_hash,
            tessera_count,
            self._tessera_size,
            self._file_size,
            last_tessera_size,
            len(metadata_bytes),
        )
        return header + metadata_bytes + b"".join(self._leaf_hashes)

    def _validate_metadata(self, meta: dict[str, str]) -> None:
        if len(meta) > self._max_metadata_keys:
            raise ConfigError(
                "metadata",
                f"too many keys ({len(meta)}), max is {self._max_metadata_keys}",
            )
        for key, value in meta.items():
            val_bytes = value.encode()
            if len(val_bytes) > self._max_metadata_value_bytes:
                raise ConfigError(
                    f"metadata[{key!r}]",
                    f"value too long ({len(val_bytes)} bytes), "
                    f"max is {self._max_metadata_value_bytes}",
                )


class ManifestParser:
    """Parses and verifies serialized manifest bytes.

    All checks from ts-spec-006 §7 Level 1 verification are performed.
    """

    @staticmethod
    def parse(
        manifest_bytes: bytes,
        trusted_hash: bytes | None = None,
    ) -> ManifestInfo:
        """Parse *manifest_bytes* and return a ManifestInfo.

        Args:
            manifest_bytes: Raw manifest as produced by ManifestBuilder.build().
            trusted_hash: If provided, verify SHA-256(manifest_bytes) matches.
                          Raises ValueError on mismatch (T2 mitigation).

        Returns:
            ManifestInfo with all fields populated.

        Raises:
            ValueError: On magic mismatch, unknown version, structural
                        inconsistency, or trusted_hash mismatch.
        """
        manifest_hash = hashlib.sha256(manifest_bytes).digest()

        if trusted_hash is not None and manifest_hash != trusted_hash:
            raise ValueError(
                "manifest hash mismatch: "
                f"expected {trusted_hash.hex()}, got {manifest_hash.hex()}"
            )

        if len(manifest_bytes) < _HEADER_SIZE:
            raise ValueError(
                f"manifest too short: {len(manifest_bytes)} < {_HEADER_SIZE}"
            )

        (
            magic,
            format_version,
            root_hash,
            tessera_count,
            tessera_size,
            file_size,
            last_tessera_size,
            metadata_len,
        ) = struct.unpack_from(_HEADER_FMT, manifest_bytes, 0)

        if magic != MAGIC:
            raise ValueError(
                f"invalid manifest magic: expected {MAGIC!r}, got {magic!r}"
            )
        if format_version != FORMAT_VERSION:
            raise ValueError(
                f"unsupported manifest format version: 0x{format_version:04X}"
            )

        meta_start = _HEADER_SIZE
        meta_end = meta_start + metadata_len
        leaf_start = meta_end
        leaf_end = leaf_start + 32 * tessera_count

        if len(manifest_bytes) < leaf_end:
            raise ValueError(
                f"manifest truncated: need {leaf_end} bytes, got {len(manifest_bytes)}"
            )

        metadata = _decode_metadata(manifest_bytes[meta_start:meta_end])

        leaf_hashes: list[bytes] = [
            manifest_bytes[leaf_start + i * 32 : leaf_start + (i + 1) * 32]
            for i in range(tessera_count)
        ]

        # Structural consistency checks.
        if tessera_count == 0:
            if file_size != 0:
                raise ValueError(
                    f"tessera_count=0 but file_size={file_size} (must be 0)"
                )
        elif tessera_count == 1:
            if file_size != last_tessera_size:
                raise ValueError(
                    f"tessera_count=1: file_size ({file_size}) "
                    f"!= last_tessera_size ({last_tessera_size})"
                )
        else:
            expected_size = (tessera_count - 1) * tessera_size + last_tessera_size
            if file_size != expected_size:
                raise ValueError(
                    f"file_size ({file_size}) inconsistent with "
                    f"tessera geometry (expected {expected_size})"
                )

        if last_tessera_size > tessera_size:
            raise ValueError(
                f"last_tessera_size ({last_tessera_size}) "
                f"> tessera_size ({tessera_size})"
            )

        # Verify Merkle root.
        computed_root = build_root(leaf_hashes)
        if computed_root != root_hash:
            raise ValueError(
                "manifest root_hash is internally inconsistent "
                f"(computed {computed_root.hex()}, stored {root_hash.hex()})"
            )

        return ManifestInfo(
            manifest_hash=manifest_hash,
            root_hash=root_hash,
            tessera_count=tessera_count,
            tessera_size=tessera_size,
            file_size=file_size,
            last_tessera_size=last_tessera_size,
            metadata=metadata,
            leaf_hashes=leaf_hashes,
        )


# ---------------------------------------------------------------------------
# Metadata encoding helpers
# ---------------------------------------------------------------------------


def _encode_metadata(meta: dict[str, str]) -> bytes:
    """Encode sorted key-value pairs to bytes."""
    buf = bytearray()
    for key, value in sorted(meta.items()):
        k = key.encode()
        v = value.encode()
        buf.append(len(k))
        buf.extend(k)
        buf.extend(struct.pack("!H", len(v)))
        buf.extend(v)
    return bytes(buf)


def _decode_metadata(data: bytes) -> dict[str, str]:
    """Decode a metadata blob produced by _encode_metadata."""
    meta: dict[str, str] = {}
    pos = 0
    while pos < len(data):
        key_len = data[pos]
        pos += 1
        key = data[pos : pos + key_len].decode()
        pos += key_len
        (val_len,) = struct.unpack_from("!H", data, pos)
        pos += 2
        value = data[pos : pos + val_len].decode()
        pos += val_len
        meta[key] = value
    return meta
