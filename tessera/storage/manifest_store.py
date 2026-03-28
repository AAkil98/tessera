"""Manifest persistence and in-memory discovery index.

Spec: ts-spec-011 §3

Manifests are write-once, content-addressed. The store never modifies an
existing manifest file — it either writes a new one or skips if already
present. Every read verifies the SHA-256 hash to catch silent corruption.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path

from tessera.content.manifest import ManifestParser
from tessera.storage.layout import make_tmp_path, manifest_path

log = logging.getLogger(__name__)


class ManifestIndex:
    """In-memory index mapping manifest hashes to their metadata.

    Used by the AI Discovery Adapter (ts-spec-009) for natural-language
    search without deserializing every manifest on disk.

    Rebuilt from disk on every TesseraNode.start(). Not persisted —
    the manifests themselves are the source of truth.
    """

    def __init__(self) -> None:
        self._index: dict[bytes, dict[str, str]] = {}

    def rebuild(self, data_dir: Path) -> None:
        """Scan manifests/ and repopulate the index."""
        self._index.clear()
        manifests_dir = data_dir.expanduser() / "manifests"
        if not manifests_dir.exists():
            return
        for prefix_dir in manifests_dir.iterdir():
            if not prefix_dir.is_dir():
                continue
            for mfile in prefix_dir.glob("*.manifest"):
                try:
                    raw = mfile.read_bytes()
                    expected_hash = bytes.fromhex(mfile.stem)
                    if hashlib.sha256(raw).digest() != expected_hash:
                        log.warning(
                            "Skipping corrupt manifest in index rebuild: %s",
                            mfile,
                        )
                        continue
                    info = ManifestParser.parse(raw)
                    self._index[expected_hash] = info.metadata
                except Exception:
                    log.warning(
                        "Failed to parse manifest during index rebuild: %s",
                        mfile,
                        exc_info=True,
                    )

    def add(self, manifest_hash: bytes, metadata: dict[str, str]) -> None:
        """Register a manifest in the index (called after a successful write)."""
        self._index[manifest_hash] = metadata

    def remove(self, manifest_hash: bytes) -> None:
        """Remove a manifest from the index (called during GC)."""
        self._index.pop(manifest_hash, None)

    def all_metadata(self) -> list[tuple[bytes, dict[str, str]]]:
        """Return all (manifest_hash, metadata) pairs for LLM search."""
        return list(self._index.items())


class ManifestStore:
    """Persist and retrieve serialized manifests.

    Args:
        data_dir: Root Tessera data directory (ts-spec-011 §2).
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser()
        self.index = ManifestIndex()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def write(self, manifest_bytes: bytes) -> bytes:
        """Write *manifest_bytes* to disk and update the in-memory index.

        Returns:
            The manifest hash (SHA-256 of *manifest_bytes*).

        Skips the write if the manifest is already on disk (idempotent).
        """
        manifest_hash, metadata = await asyncio.to_thread(
            self._write_sync, manifest_bytes
        )
        self.index.add(manifest_hash, metadata)
        return manifest_hash

    def _write_sync(self, manifest_bytes: bytes) -> tuple[bytes, dict[str, str]]:
        manifest_hash = hashlib.sha256(manifest_bytes).digest()
        target = manifest_path(self._data_dir, manifest_hash)

        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = make_tmp_path(self._data_dir, ".manifest")
            try:
                tmp.write_bytes(manifest_bytes)
                os.rename(tmp, target)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise

        info = ManifestParser.parse(manifest_bytes)
        return manifest_hash, info.metadata

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def read(self, manifest_hash: bytes) -> bytes | None:
        """Return the raw manifest bytes, or None if missing or corrupt."""
        return await asyncio.to_thread(self._read_sync, manifest_hash)

    def _read_sync(self, manifest_hash: bytes) -> bytes | None:
        target = manifest_path(self._data_dir, manifest_hash)
        if not target.exists():
            return None
        raw = target.read_bytes()
        if hashlib.sha256(raw).digest() != manifest_hash:
            log.warning("Corrupt manifest %s — deleting", manifest_hash.hex())
            target.unlink(missing_ok=True)
            return None
        return raw

    # ------------------------------------------------------------------
    # Index rebuild
    # ------------------------------------------------------------------

    async def rebuild_index(self) -> None:
        """Rebuild the in-memory index by scanning manifests/ on disk."""
        await asyncio.to_thread(self.index.rebuild, self._data_dir)

    # ------------------------------------------------------------------
    # Delete (GC support)
    # ------------------------------------------------------------------

    async def delete(self, manifest_hash: bytes) -> None:
        """Delete the manifest file from disk and remove it from the index."""
        await asyncio.to_thread(self._delete_sync, manifest_hash)
        self.index.remove(manifest_hash)

    def _delete_sync(self, manifest_hash: bytes) -> None:
        manifest_path(self._data_dir, manifest_hash).unlink(missing_ok=True)
