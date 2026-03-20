"""Garbage collection — reclaim disk space from completed or cancelled mosaics.

Spec: ts-spec-011 §7

Collection is explicit (never automatic during an active transfer).
The 60-second grace period is enforced here via the *completed_at* /
*grace_period* parameters; callers pass the completion timestamp.

Collection procedure (in order):
  1. Verify eligibility (role, grace period).
  2. Delete the state file.
  3. Delete all piece files and the mosaic directory.
  4. Remove from the manifest index.
  5. Optionally delete the manifest file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from tessera.storage.layout import manifest_path, state_path, tessera_dir
from tessera.storage.manifest_store import ManifestIndex
from tessera.storage.state import TransferState, read_state

log = logging.getLogger(__name__)

_GRACE_PERIOD_SECONDS: float = 60.0


class GarbageCollector:
    """Collect on-disk data for mosaics that are no longer needed.

    Args:
        data_dir: Root Tessera data directory.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.expanduser()

    async def collect(
        self,
        manifest_hash: bytes,
        *,
        retain_manifests: bool = True,
        manifest_index: ManifestIndex | None = None,
        completed_at: float | None = None,
        grace_period: float = _GRACE_PERIOD_SECONDS,
        force: bool = False,
    ) -> bool:
        """Collect all on-disk data for *manifest_hash*.

        Args:
            manifest_hash: Mosaic to collect.
            retain_manifests: If True (default), the .manifest file is kept.
            manifest_index: In-memory index to update after deletion.
            completed_at: Unix timestamp when the transfer completed.
                          If provided, collection is skipped if within
                          *grace_period* seconds.
            grace_period: Seconds after completion before data is eligible.
            force: If True, skip the seeder-role and grace-period checks.

        Returns:
            True if collection ran; False if skipped (grace period or seeder).
        """
        if not force:
            # Grace-period check.
            if completed_at is not None:
                age = time.time() - completed_at
                if age < grace_period:
                    log.debug(
                        "GC skipped for %s: within grace period (%.1fs < %.1fs)",
                        manifest_hash.hex()[:8],
                        age,
                        grace_period,
                    )
                    return False

            # Seeder-role check: never collect actively seeding data.
            state: TransferState | None = await read_state(
                self._data_dir, manifest_hash
            )
            if state is not None and state.role == "seeder":
                log.debug(
                    "GC skipped for %s: role is seeder",
                    manifest_hash.hex()[:8],
                )
                return False

        await asyncio.to_thread(
            self._collect_sync,
            manifest_hash,
            retain_manifests,
            manifest_index,
        )
        return True

    def _collect_sync(
        self,
        manifest_hash: bytes,
        retain_manifests: bool,
        manifest_index: ManifestIndex | None,
    ) -> None:
        import shutil

        hex_hash = manifest_hash.hex()

        # 1. Delete the state file.
        sp = state_path(self._data_dir, manifest_hash)
        sp.unlink(missing_ok=True)
        log.debug("GC: deleted state file for %s", hex_hash[:8])

        # 2-3. Delete piece files and tessera directory.
        td = tessera_dir(self._data_dir, manifest_hash)
        if td.exists():
            shutil.rmtree(td, ignore_errors=True)
            log.debug("GC: deleted tessera directory %s", td)

        # 4. Update the manifest index.
        if manifest_index is not None:
            manifest_index.remove(manifest_hash)

        # 5. Optionally delete the manifest file.
        if not retain_manifests:
            mp = manifest_path(self._data_dir, manifest_hash)
            mp.unlink(missing_ok=True)
            log.debug("GC: deleted manifest for %s", hex_hash[:8])
