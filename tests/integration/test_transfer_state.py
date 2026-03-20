"""Integration tests: transfer state and resume — ts-spec-013 §4.3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tessera.content.bitfield import Bitfield
from tessera.storage.layout import ensure_data_dir
from tessera.storage.state import (
    TransferState,
    delete_state,
    read_state,
    write_state,
)
from tessera.storage.tessera_store import TesseraStore

_HASH = b"\xaa" * 32
_COUNT = 200


def _full_bitfield(count: int) -> Bitfield:
    bf = Bitfield(count)
    for i in range(count):
        bf.set(i)
    return bf


def _partial_bitfield(count: int, n_set: int) -> Bitfield:
    bf = Bitfield(count)
    for i in range(n_set):
        bf.set(i)
    return bf


@pytest.mark.integration
async def test_state_file_json_valid(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_HASH, _COUNT)
    await write_state(tmp_path, state)
    from tessera.storage.layout import state_path

    raw = json.loads(state_path(tmp_path, _HASH).read_text())
    assert raw["version"] == 1
    assert raw["manifest_hash"] == _HASH.hex()
    assert raw["role"] == "fetcher"
    assert "bitfield" in raw
    assert "retry_counts" in raw


@pytest.mark.integration
async def test_resume_from_state(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    bf = _partial_bitfield(_COUNT, 100)
    state = TransferState.for_fetcher(_HASH, _COUNT)
    state.set_bitfield(bf)
    await write_state(tmp_path, state)

    loaded = await read_state(tmp_path, _HASH)
    assert loaded is not None
    assert loaded.role == "fetcher"
    assert loaded.tessera_count == _COUNT
    restored_bf = loaded.get_bitfield()
    assert restored_bf.count_set() == 100


@pytest.mark.integration
async def test_resume_disk_authoritative(tmp_path: Path) -> None:
    """Disk-derived bitfield wins over the saved state bitfield."""
    ensure_data_dir(tmp_path)
    # State says 90 pieces done.
    state = TransferState.for_fetcher(_HASH, _COUNT)
    state.set_bitfield(_partial_bitfield(_COUNT, 90))
    await write_state(tmp_path, state)

    # Physically write 100 pieces.
    ts = TesseraStore(tmp_path)
    for i in range(100):
        await ts.write(_HASH, i, bytes([i % 256]) * 10)

    disk_bf = await ts.rebuild_bitfield(_HASH, _COUNT)
    assert disk_bf.count_set() == 100


@pytest.mark.integration
async def test_resume_disk_fewer_than_state(tmp_path: Path) -> None:
    """State says 100, disk has 95 — disk wins."""
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_HASH, _COUNT)
    state.set_bitfield(_partial_bitfield(_COUNT, 100))
    await write_state(tmp_path, state)

    ts = TesseraStore(tmp_path)
    for i in range(95):
        await ts.write(_HASH, i, b"x" * 10)

    disk_bf = await ts.rebuild_bitfield(_HASH, _COUNT)
    assert disk_bf.count_set() == 95


@pytest.mark.integration
async def test_resume_missing_manifest(tmp_path: Path) -> None:
    """State file exists but manifest missing → startup_cleanup deletes state."""
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_HASH, _COUNT)
    await write_state(tmp_path, state)

    from tessera.storage.layout import startup_cleanup, state_path

    # No manifest written — startup_cleanup should delete the state file.
    startup_cleanup(tmp_path)
    assert not state_path(tmp_path, _HASH).exists()


@pytest.mark.integration
async def test_delete_state(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_HASH, _COUNT)
    await write_state(tmp_path, state)
    assert await read_state(tmp_path, _HASH) is not None
    await delete_state(tmp_path, _HASH)
    assert await read_state(tmp_path, _HASH) is None
