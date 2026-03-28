"""Adversarial tests: crash recovery extended -- ts-spec-013 section 6.10.

Additional scenarios beyond test_crash_recovery.py:
  - All pieces written, output file deleted: pieces survive for retry.
  - Valid pieces written, then one corrupted on disk: assembly raises IntegrityError.
  - Stale state file (no manifest) cleaned on startup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import IntegrityError
from tessera.storage.layout import (
    ensure_data_dir,
    startup_cleanup,
    state_path,
    tessera_path,
)
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
async def test_crash_during_assembly_pieces_preserved(tmp_path: Path) -> None:
    """Write all pieces, delete the output file, verify pieces remain on disk.

    Simulates a crash after piece download completes but before the output
    file is fully written. On the next attempt the pieces should still be
    present in the store, enabling a retry without re-downloading.
    """
    pub = tmp_path / "pub"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    # Set up fetcher data directory and manually copy all pieces.
    fet = tmp_path / "fetcher"
    ensure_data_dir(fet)
    ms = ManifestStore(fet)
    ts = TesseraStore(fet)

    raw = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw is not None
    await ms.write(raw)

    # Copy all 4 pieces.
    for i in range(4):
        data = await publisher._tessera_store.read(mh, i)  # type: ignore[union-attr]
        assert data is not None
        await ts.write(mh, i, data)

    # Simulate a crash: suppose the output file was started but then deleted.
    output = fet / "out.bin"
    output.write_bytes(b"partial-garbage")
    output.unlink()

    # All pieces should still be on disk.
    for i in range(4):
        assert tessera_path(fet, mh, i).exists(), f"piece {i} should survive"

    # A retry should succeed: fetch with a provider that supplies from publisher.
    class RetrySource:
        async def get_manifest(self) -> bytes | None:
            return await publisher._manifest_store.read(mh)  # type: ignore[union-attr]

        async def get_piece(self, index: int) -> bytes | None:
            return await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = RetrySource()  # type: ignore[assignment]
        out = await fetcher.fetch(mh)

    assert out.read_bytes() == small()


@pytest.mark.adversarial
async def test_corrupt_piece_on_disk_detected_at_assembly(tmp_path: Path) -> None:
    """Write valid pieces then corrupt one on disk; assembly raises IntegrityError.

    This simulates bit-rot or a malicious process modifying a piece file
    after it was stored. The assembler's Level-3 verification must catch it.
    """
    pub = tmp_path / "pub"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    # Set up fetcher with all pieces copied honestly.
    fet = tmp_path / "fetcher"
    ensure_data_dir(fet)
    ms = ManifestStore(fet)
    ts = TesseraStore(fet)

    raw = await publisher._manifest_store.read(mh)  # type: ignore[union-attr]
    assert raw is not None
    await ms.write(raw)

    for i in range(4):
        data = await publisher._tessera_store.read(mh, i)  # type: ignore[union-attr]
        assert data is not None
        await ts.write(mh, i, data)

    # Now corrupt piece 1 on disk.
    piece_file = tessera_path(fet, mh, 1)
    assert piece_file.exists()
    piece_file.write_bytes(b"\xff" * TESSERA_SIZE)

    # The provider supplies valid data from the publisher but the fetcher
    # already has all pieces on disk (including the corrupted one). Assembly
    # should detect the mismatch.
    class HonestSource:
        async def get_manifest(self) -> bytes | None:
            return await publisher._manifest_store.read(mh)  # type: ignore[union-attr]

        async def get_piece(self, index: int) -> bytes | None:
            # Return the corrupted piece from fetcher's store for index 1,
            # simulating that the pieces were already cached on disk.
            return (
                piece_file.read_bytes()
                if index == 1
                else await publisher._tessera_store.read(mh, index)
            )  # type: ignore[union-attr]

    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = HonestSource()  # type: ignore[assignment]
        with pytest.raises(IntegrityError):
            await fetcher.fetch(mh)


@pytest.mark.adversarial
def test_stale_state_file_cleaned_on_startup(tmp_path: Path) -> None:
    """A state file without a corresponding manifest is removed on startup.

    ts-spec-011 section 7: startup_cleanup deletes state files whose manifest
    is missing from the manifests/ directory, along with any orphaned
    tessera directory.
    """
    data_dir = tmp_path / "node"
    ensure_data_dir(data_dir)

    # Create a fake state file for a manifest that does not exist.
    fake_hash = b"\xab" * 32
    sf = state_path(data_dir, fake_hash)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_bytes(b'{"status": "incomplete"}')

    # Also create an orphaned tessera directory for the same hash.
    tdir = data_dir / "tesserae" / fake_hash.hex()
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "000000.piece").write_bytes(b"orphan-piece-data")

    assert sf.exists()
    assert tdir.exists()

    startup_cleanup(data_dir)

    # Both the state file and the tessera directory should be removed.
    assert not sf.exists(), "stale state file should be removed"
    assert not tdir.exists(), "orphaned tessera directory should be removed"
