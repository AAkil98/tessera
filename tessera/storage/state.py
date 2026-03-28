"""Transfer state persistence and resume support.

Spec: ts-spec-011 §5

Each active transfer (publisher or fetcher) has a .state file in
transfers/. The file is written atomically (write-to-tmp-then-rename)
and is the basis for resumption after a crash or restart.

State files are small JSON documents that are human-readable for
debugging. The bitfield is stored as URL-safe base64.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tessera.content.bitfield import Bitfield
from tessera.storage.layout import make_tmp_path, state_path

log = logging.getLogger(__name__)

# Write state every N% of total tesserae completed.
STATE_WRITE_INTERVAL_PCT: float = 0.05  # 5%


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class TransferState:
    """In-memory representation of a transfer's on-disk state.

    Attributes mirror the JSON state file format (ts-spec-011 §5).
    """

    version: int = 1
    manifest_hash: bytes = field(default_factory=bytes)
    role: str = "fetcher"  # "seeder" | "fetcher"
    tessera_count: int = 0
    _bitfield_b64: str = field(default="", repr=False)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    bytes_downloaded: int = 0
    retry_counts: dict[str, int] = field(default_factory=dict)
    stuck_tesserae: list[int] = field(default_factory=list)
    peers_seen: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Bitfield helpers
    # ------------------------------------------------------------------

    def get_bitfield(self) -> Bitfield:
        """Return the current bitfield, reconstructing from base64."""
        if not self._bitfield_b64:
            return Bitfield(self.tessera_count)
        return Bitfield.from_base64(self.tessera_count, self._bitfield_b64)

    def set_bitfield(self, bf: Bitfield) -> None:
        """Store *bf* as base64 in the state."""
        self._bitfield_b64 = bf.to_base64()

    def touch(self) -> None:
        """Update updated_at to now."""
        self.updated_at = _utcnow()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        """Serialize to the JSON wire format (ts-spec-011 §5)."""
        return json.dumps(
            {
                "version": self.version,
                "manifest_hash": self.manifest_hash.hex(),
                "role": self.role,
                "tessera_count": self.tessera_count,
                "bitfield": self._bitfield_b64,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "bytes_downloaded": self.bytes_downloaded,
                "retry_counts": self.retry_counts,
                "stuck_tesserae": self.stuck_tesserae,
                "peers_seen": self.peers_seen,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> TransferState:
        """Deserialize from a JSON state file."""
        d: dict[str, Any] = json.loads(text)
        obj = cls(
            version=int(d["version"]),
            manifest_hash=bytes.fromhex(str(d["manifest_hash"])),
            role=str(d["role"]),
            tessera_count=int(d["tessera_count"]),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            bytes_downloaded=int(d.get("bytes_downloaded", 0)),
            retry_counts={
                str(k): int(v) for k, v in (d.get("retry_counts") or {}).items()
            },
            stuck_tesserae=[int(i) for i in (d.get("stuck_tesserae") or [])],
            peers_seen=[str(p) for p in (d.get("peers_seen") or [])],
        )
        obj._bitfield_b64 = str(d.get("bitfield", ""))
        return obj

    @classmethod
    def for_seeder(
        cls,
        manifest_hash: bytes,
        tessera_count: int,
    ) -> TransferState:
        """Create a complete seeder state (all bits set)."""
        bf = Bitfield(tessera_count)
        for i in range(tessera_count):
            bf.set(i)
        state = cls(
            manifest_hash=manifest_hash,
            role="seeder",
            tessera_count=tessera_count,
        )
        state.set_bitfield(bf)
        return state

    @classmethod
    def for_fetcher(
        cls,
        manifest_hash: bytes,
        tessera_count: int,
    ) -> TransferState:
        """Create a fresh fetcher state (no bits set)."""
        return cls(
            manifest_hash=manifest_hash,
            role="fetcher",
            tessera_count=tessera_count,
        )


# ---------------------------------------------------------------------------
# Async I/O helpers
# ---------------------------------------------------------------------------


async def write_state(data_dir: Path, state: TransferState) -> None:
    """Persist *state* to disk atomically."""
    state.touch()
    await asyncio.to_thread(_write_state_sync, data_dir, state)


def _write_state_sync(data_dir: Path, state: TransferState) -> None:
    raw = state.to_json().encode()
    tmp = make_tmp_path(data_dir, ".state")
    target = state_path(data_dir, state.manifest_hash)
    try:
        tmp.write_bytes(raw)
        os.rename(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def read_state(data_dir: Path, manifest_hash: bytes) -> TransferState | None:
    """Load a state file from disk; return None if missing or malformed."""
    return await asyncio.to_thread(_read_state_sync, data_dir, manifest_hash)


def _read_state_sync(data_dir: Path, manifest_hash: bytes) -> TransferState | None:
    sp = state_path(data_dir, manifest_hash)
    if not sp.exists():
        return None
    try:
        return TransferState.from_json(sp.read_text())
    except Exception:
        log.warning("Malformed state file %s — ignoring", sp, exc_info=True)
        return None


async def delete_state(data_dir: Path, manifest_hash: bytes) -> None:
    """Delete the state file for *manifest_hash*."""
    await asyncio.to_thread(
        lambda: state_path(data_dir, manifest_hash).unlink(missing_ok=True)
    )
