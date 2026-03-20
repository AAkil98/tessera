"""Tessera piece persistence and mosaic assembly.

Spec: ts-spec-011 §4, §6

Every write follows write-to-tmp-then-rename for crash safety.
Content-addressability means duplicate writes (endgame mode) are free —
if the piece file already exists at the target path, the write is skipped.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path

from tessera.content.bitfield import Bitfield
from tessera.errors import IntegrityError
from tessera.storage.layout import (
    make_tmp_path,
    tessera_dir,
    tessera_path,
)
from tessera.types import ManifestInfo

log = logging.getLogger(__name__)


class TesseraStore:
    """Read and write tessera piece files for one or more mosaics.

    Args:
        data_dir: Root Tessera data directory (ts-spec-011 §2).
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def write(
        self, manifest_hash: bytes, index: int, data: bytes
    ) -> bool:
        """Write *data* as piece *index* for *manifest_hash*.

        Returns:
            True if the piece was newly written; False if it already existed.

        Uses write-to-tmp-then-rename for crash safety. If the target file
        already exists the write is skipped (handles endgame duplicates).
        """
        return await asyncio.to_thread(
            self._write_sync, manifest_hash, index, data
        )

    def _write_sync(
        self, manifest_hash: bytes, index: int, data: bytes
    ) -> bool:
        target = tessera_path(self._data_dir, manifest_hash, index)
        if target.exists():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = make_tmp_path(self._data_dir, ".piece")
        try:
            tmp.write_bytes(data)
            os.rename(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def read(
        self, manifest_hash: bytes, index: int
    ) -> bytes | None:
        """Return the raw piece bytes, or None if the piece is not on disk."""
        return await asyncio.to_thread(
            self._read_sync, manifest_hash, index
        )

    def _read_sync(
        self, manifest_hash: bytes, index: int
    ) -> bytes | None:
        target = tessera_path(self._data_dir, manifest_hash, index)
        if not target.exists():
            return None
        return target.read_bytes()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def exists(self, manifest_hash: bytes, index: int) -> bool:
        """Return True if the piece file for *index* exists on disk."""
        return tessera_path(self._data_dir, manifest_hash, index).exists()

    async def count(self, manifest_hash: bytes) -> int:
        """Count how many piece files exist for *manifest_hash*."""
        return await asyncio.to_thread(self._count_sync, manifest_hash)

    def _count_sync(self, manifest_hash: bytes) -> int:
        td = tessera_dir(self._data_dir, manifest_hash)
        if not td.exists():
            return 0
        return sum(1 for _ in td.glob("*.piece"))

    async def rebuild_bitfield(
        self, manifest_hash: bytes, tessera_count: int
    ) -> Bitfield:
        """Build a Bitfield by scanning piece files on disk.

        The disk-derived bitfield is authoritative over any stored state —
        it reflects exactly which pieces are present after a crash.
        """
        return await asyncio.to_thread(
            self._rebuild_sync, manifest_hash, tessera_count
        )

    def _rebuild_sync(
        self, manifest_hash: bytes, tessera_count: int
    ) -> Bitfield:
        bf = Bitfield(tessera_count)
        td = tessera_dir(self._data_dir, manifest_hash)
        if not td.exists():
            return bf
        for piece_file in td.glob("*.piece"):
            try:
                idx = int(piece_file.stem)
                if 0 <= idx < tessera_count:
                    bf.set(idx)
            except ValueError:
                pass
        return bf

    # ------------------------------------------------------------------
    # Assembly  (ts-spec-011 §4, ts-spec-006 §7 level-3 verification)
    # ------------------------------------------------------------------

    async def assemble(
        self,
        manifest_hash: bytes,
        manifest_info: ManifestInfo,
        output_path: Path,
    ) -> None:
        """Assemble all tesserae into *output_path* and verify integrity.

        Reads piece files in index order, writes them sequentially to
        *output_path*, then re-hashes each chunk against the manifest's
        leaf hashes (ts-spec-006 §7 Level-3 whole-file verification).

        Raises:
            IntegrityError: If any tessera's hash does not match the
                manifest's leaf hash for that index.
        """
        await asyncio.to_thread(
            self._assemble_sync, manifest_hash, manifest_info, output_path
        )

    def _assemble_sync(
        self,
        manifest_hash: bytes,
        manifest_info: ManifestInfo,
        output_path: Path,
    ) -> None:
        if manifest_info.tessera_count == 0:
            output_path.write_bytes(b"")
            return

        with open(output_path, "wb") as out:
            for i in range(manifest_info.tessera_count):
                data = tessera_path(
                    self._data_dir, manifest_hash, i
                ).read_bytes()
                out.write(data)

        # Level-3 verification: re-read and hash each chunk.
        with open(output_path, "rb") as f:
            for i in range(manifest_info.tessera_count):
                expected_size = (
                    manifest_info.tessera_size
                    if i < manifest_info.tessera_count - 1
                    else manifest_info.last_tessera_size
                )
                chunk = f.read(expected_size)
                actual = hashlib.sha256(chunk).digest()
                if actual != manifest_info.leaf_hashes[i]:
                    raise IntegrityError(
                        manifest_hash=manifest_hash,
                        expected=manifest_info.leaf_hashes[i],
                        actual=actual,
                    )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def delete_mosaic(self, manifest_hash: bytes) -> None:
        """Delete all piece files and the mosaic directory."""
        await asyncio.to_thread(self._delete_mosaic_sync, manifest_hash)

    def _delete_mosaic_sync(self, manifest_hash: bytes) -> None:
        import shutil

        td = tessera_dir(self._data_dir, manifest_hash)
        if td.exists():
            shutil.rmtree(td, ignore_errors=True)
