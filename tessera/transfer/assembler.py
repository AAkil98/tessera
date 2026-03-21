"""Assembler — reassemble tesserae into the final output file.

Spec: ts-spec-006 §7 Level-3 (whole-file verification), ts-spec-011 §4

The Assembler is a thin Transfer Engine wrapper over TesseraStore.assemble.
It reads piece files in index order, writes the output file, then re-hashes
each chunk against the manifest's leaf hashes (whole-file verification).

Raises IntegrityError (ts-spec-010) if any chunk fails verification.
"""

from __future__ import annotations

from pathlib import Path

from tessera.storage.tessera_store import TesseraStore
from tessera.types import ManifestInfo


class Assembler:
    """Assemble a complete mosaic into an output file.

    Args:
        store: The TesseraStore that holds the piece files.
    """

    def __init__(self, store: TesseraStore) -> None:
        self._store = store

    async def assemble(
        self,
        manifest_hash: bytes,
        manifest_info: ManifestInfo,
        output_path: Path,
    ) -> None:
        """Write all tesserae to *output_path* and verify integrity.

        Delegates to TesseraStore.assemble which performs sequential reads
        and the whole-file hash check (ts-spec-006 §7 Level-3).

        Raises:
            IntegrityError: If any tessera's hash fails verification.
            FileNotFoundError: If a piece file is missing (incomplete transfer).
        """
        await self._store.assemble(manifest_hash, manifest_info, output_path)
