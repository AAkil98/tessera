"""Integration tests: storage concurrency — ts-spec-013 §4.4."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tessera.storage.layout import ensure_data_dir, tessera_path
from tessera.storage.tessera_store import TesseraStore

_HASH_A = b"\xaa" * 32
_HASH_B = b"\xbb" * 32


@pytest.mark.integration
async def test_parallel_tessera_writes(tmp_path: Path) -> None:
    """20 concurrent piece writes → all 20 piece files exist, no partials."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    n = 20
    data = b"x" * 1024

    results = await asyncio.gather(*[ts.write(_HASH_A, i, data) for i in range(n)])
    assert all(results)  # all newly written
    for i in range(n):
        assert tessera_path(tmp_path, _HASH_A, i).exists()

    # No files remain in tmp/.
    tmp_dir = tmp_path / "tmp"
    assert list(tmp_dir.iterdir()) == []


@pytest.mark.integration
async def test_duplicate_write_idempotent(tmp_path: Path) -> None:
    """Writing the same piece twice is a no-op; content stays correct."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)
    data = b"hello"

    r1 = await ts.write(_HASH_A, 0, data)
    r2 = await ts.write(_HASH_A, 0, data)
    assert r1 is True  # first write succeeds
    assert r2 is False  # second write skipped
    assert (await ts.read(_HASH_A, 0)) == data


@pytest.mark.integration
async def test_cross_mosaic_isolation(tmp_path: Path) -> None:
    """Pieces for two mosaics never cross-contaminate each other."""
    ensure_data_dir(tmp_path)
    ts = TesseraStore(tmp_path)

    await asyncio.gather(
        *[ts.write(_HASH_A, i, bytes([i])) for i in range(5)],
        *[ts.write(_HASH_B, i, bytes([i + 100])) for i in range(5)],
    )

    for i in range(5):
        a = await ts.read(_HASH_A, i)
        b = await ts.read(_HASH_B, i)
        assert a == bytes([i])
        assert b == bytes([i + 100])


@pytest.mark.integration
async def test_tmp_cleanup_on_startup(tmp_path: Path) -> None:
    """Orphan files in tmp/ are deleted by startup_cleanup."""
    from tessera.storage.layout import startup_cleanup

    ensure_data_dir(tmp_path)
    # Manually plant orphan files in tmp/.
    tmp_dir = tmp_path / "tmp"
    (tmp_dir / "orphan1.piece").write_bytes(b"garbage")
    (tmp_dir / "orphan2.state").write_bytes(b"garbage")

    startup_cleanup(tmp_path)
    assert list(tmp_dir.iterdir()) == []
