"""Integration tests: directory layout and path derivation — ts-spec-011 §2, §7."""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.storage.layout import (
    ensure_data_dir,
    make_tmp_path,
    manifest_path,
    node_id_path,
    startup_cleanup,
    state_path,
    tessera_dir,
    tessera_path,
)

_MH = b"\xab" * 32


@pytest.mark.integration
def test_ensure_data_dir_creates_structure(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    assert (tmp_path / "manifests").is_dir()
    assert (tmp_path / "tesserae").is_dir()
    assert (tmp_path / "transfers").is_dir()
    assert (tmp_path / "tmp").is_dir()


@pytest.mark.integration
def test_ensure_data_dir_idempotent(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    ensure_data_dir(tmp_path)
    assert (tmp_path / "manifests").is_dir()


@pytest.mark.integration
def test_manifest_path_derivation(tmp_path: Path) -> None:
    p = manifest_path(tmp_path, _MH)
    hex_hash = _MH.hex()
    assert p == tmp_path / "manifests" / "ab" / f"{hex_hash}.manifest"


@pytest.mark.integration
def test_tessera_dir_derivation(tmp_path: Path) -> None:
    d = tessera_dir(tmp_path, _MH)
    assert d == tmp_path / "tesserae" / _MH.hex()


@pytest.mark.integration
def test_tessera_path_derivation(tmp_path: Path) -> None:
    p = tessera_path(tmp_path, _MH, 42)
    assert p == tmp_path / "tesserae" / _MH.hex() / "000042.piece"


@pytest.mark.integration
def test_state_path_derivation(tmp_path: Path) -> None:
    p = state_path(tmp_path, _MH)
    assert p == tmp_path / "transfers" / f"{_MH.hex()}.state"


@pytest.mark.integration
def test_node_id_path(tmp_path: Path) -> None:
    p = node_id_path(tmp_path)
    assert p == tmp_path / "node.id"


@pytest.mark.integration
def test_make_tmp_path_unique(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    p1 = make_tmp_path(tmp_path)
    p2 = make_tmp_path(tmp_path)
    assert p1 != p2
    assert p1.parent == tmp_path / "tmp"
    assert p2.parent == tmp_path / "tmp"


@pytest.mark.integration
def test_startup_cleanup_removes_tmp_files(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    leftover = tmp_path / "tmp" / "leftover.dat"
    leftover.write_bytes(b"junk")
    assert leftover.exists()
    startup_cleanup(tmp_path)
    assert not leftover.exists()


@pytest.mark.integration
def test_startup_cleanup_removes_stale_state(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    sp = state_path(tmp_path, _MH)
    sp.write_text("{}")
    assert sp.exists()
    startup_cleanup(tmp_path)
    assert not sp.exists()


@pytest.mark.integration
def test_startup_cleanup_preserves_valid_state(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    hex_hash = _MH.hex()
    # Create the manifest so the state is considered valid.
    mp = tmp_path / "manifests" / hex_hash[:2]
    mp.mkdir(parents=True, exist_ok=True)
    (mp / f"{hex_hash}.manifest").write_bytes(b"manifest-data")
    # Create the state file.
    sp = state_path(tmp_path, _MH)
    sp.write_text("{}")
    startup_cleanup(tmp_path)
    assert sp.exists()


@pytest.mark.integration
def test_startup_cleanup_removes_tesserae_of_stale_state(tmp_path: Path) -> None:
    ensure_data_dir(tmp_path)
    hex_hash = _MH.hex()
    # Create a state file with no matching manifest (stale).
    sp = state_path(tmp_path, _MH)
    sp.write_text("{}")
    # Create the tessera directory for the same hash.
    td = tmp_path / "tesserae" / hex_hash
    td.mkdir(parents=True, exist_ok=True)
    (td / "000000.piece").write_bytes(b"piece-data")
    assert sp.exists()
    assert td.exists()
    startup_cleanup(tmp_path)
    assert not sp.exists()
    assert not td.exists()
