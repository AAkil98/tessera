"""Integration tests: TransferState class and I/O — ts-spec-011 §5."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tessera.content.bitfield import Bitfield
from tessera.storage.layout import ensure_data_dir, state_path
from tessera.storage.state import (
    TransferState,
    delete_state,
    read_state,
    write_state,
)

_MH = b"\xcc" * 32
_COUNT = 64


@pytest.mark.integration
def test_to_json_from_json_roundtrip() -> None:
    state = TransferState.for_fetcher(_MH, _COUNT)
    state.bytes_downloaded = 9999
    state.peers_seen = ["peer-a", "peer-b"]
    text = state.to_json()
    restored = TransferState.from_json(text)
    assert restored.manifest_hash == state.manifest_hash
    assert restored.role == state.role
    assert restored.tessera_count == state.tessera_count
    assert restored.bytes_downloaded == state.bytes_downloaded
    assert restored.peers_seen == state.peers_seen
    assert restored.created_at == state.created_at
    assert restored.updated_at == state.updated_at


@pytest.mark.integration
def test_for_seeder_factory() -> None:
    state = TransferState.for_seeder(_MH, _COUNT)
    assert state.role == "seeder"
    bf = state.get_bitfield()
    assert bf.is_complete()
    assert bf.count_set() == _COUNT


@pytest.mark.integration
def test_for_fetcher_factory() -> None:
    state = TransferState.for_fetcher(_MH, _COUNT)
    assert state.role == "fetcher"
    bf = state.get_bitfield()
    assert bf.count_set() == 0


@pytest.mark.integration
def test_bitfield_get_set_roundtrip() -> None:
    state = TransferState.for_fetcher(_MH, _COUNT)
    bf = Bitfield(_COUNT)
    for i in (0, 5, 13, 63):
        bf.set(i)
    state.set_bitfield(bf)
    restored = state.get_bitfield()
    assert restored.count_set() == 4
    for i in (0, 5, 13, 63):
        assert restored.get(i)
    for i in (1, 6, 14, 62):
        assert not restored.get(i)


@pytest.mark.integration
def test_touch_updates_timestamp() -> None:
    state = TransferState.for_fetcher(_MH, _COUNT)
    old_ts = state.updated_at
    # Ensure at least 1 second elapses so the ISO timestamp differs.
    time.sleep(1.1)
    state.touch()
    assert state.updated_at != old_ts


@pytest.mark.integration
async def test_write_state_creates_file(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_MH, _COUNT)
    await write_state(tmp_path, state)
    sp = state_path(tmp_path, _MH)
    assert sp.exists()


@pytest.mark.integration
async def test_read_state_returns_correct_data(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    state = TransferState.for_seeder(_MH, _COUNT)
    state.bytes_downloaded = 12345
    await write_state(tmp_path, state)
    loaded = await read_state(tmp_path, _MH)
    assert loaded is not None
    assert loaded.manifest_hash == _MH
    assert loaded.role == "seeder"
    assert loaded.tessera_count == _COUNT
    assert loaded.bytes_downloaded == 12345


@pytest.mark.integration
async def test_read_state_returns_none_missing(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    result = await read_state(tmp_path, _MH)
    assert result is None


@pytest.mark.integration
async def test_delete_state_removes_file(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    state = TransferState.for_fetcher(_MH, _COUNT)
    await write_state(tmp_path, state)
    sp = state_path(tmp_path, _MH)
    assert sp.exists()
    await delete_state(tmp_path, _MH)
    assert not sp.exists()


@pytest.mark.integration
async def test_from_json_malformed_returns_none_via_read(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    sp = state_path(tmp_path, _MH)
    sp.write_text("NOT VALID JSON {{{")
    result = await read_state(tmp_path, _MH)
    assert result is None


@pytest.mark.integration
def test_state_json_is_valid_json() -> None:
    state = TransferState.for_fetcher(_MH, _COUNT)
    text = state.to_json()
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    assert "version" in parsed
    assert "manifest_hash" in parsed


@pytest.mark.integration
def test_bitfield_base64_in_json() -> None:
    state = TransferState.for_seeder(_MH, _COUNT)
    text = state.to_json()
    parsed = json.loads(text)
    bf_value = parsed["bitfield"]
    assert isinstance(bf_value, str)
    assert len(bf_value) > 0
