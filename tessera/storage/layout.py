"""Directory layout, path derivation, and startup housekeeping.

Spec: ts-spec-011 §2, §7

All state lives under data_dir (~/.tessera by default):

  manifests/{hash[0:2]}/{hash_hex}.manifest
  tesserae/{manifest_hash_hex}/{index:06d}.piece
  transfers/{manifest_hash_hex}.state
  tmp/                    ← atomic write staging area
  node.id                 ← persistent node identity seed
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_DIR_MODE: int = 0o700


def ensure_data_dir(data_dir: Path) -> None:
    """Create the full directory tree under *data_dir*.

    Idempotent — safe to call on an existing data_dir.
    Directories are created with mode 0700.
    """
    root = data_dir.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, _DIR_MODE)
    for subdir in ("manifests", "tesserae", "transfers", "tmp"):
        d = root / subdir
        d.mkdir(exist_ok=True)
        os.chmod(d, _DIR_MODE)


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------


def manifest_path(data_dir: Path, manifest_hash: bytes) -> Path:
    """Canonical path for a manifest file.

    Example: hash a3f2…c891 → manifests/a3/a3f2…c891.manifest
    """
    hex_hash = manifest_hash.hex()
    return (
        data_dir.expanduser()
        / "manifests"
        / hex_hash[:2]
        / f"{hex_hash}.manifest"
    )


def tessera_dir(data_dir: Path, manifest_hash: bytes) -> Path:
    """Directory holding all piece files for one mosaic."""
    return data_dir.expanduser() / "tesserae" / manifest_hash.hex()


def tessera_path(data_dir: Path, manifest_hash: bytes, index: int) -> Path:
    """Path for a single tessera piece file (zero-padded 6-digit index)."""
    return tessera_dir(data_dir, manifest_hash) / f"{index:06d}.piece"


def state_path(data_dir: Path, manifest_hash: bytes) -> Path:
    """Path for a transfer state file."""
    return (
        data_dir.expanduser() / "transfers" / f"{manifest_hash.hex()}.state"
    )


def node_id_path(data_dir: Path) -> Path:
    return data_dir.expanduser() / "node.id"


def make_tmp_path(data_dir: Path, suffix: str = "") -> Path:
    """Return a unique path inside tmp/ suitable for atomic writes."""
    return data_dir.expanduser() / "tmp" / f"{uuid.uuid4().hex}{suffix}"


# ---------------------------------------------------------------------------
# Startup housekeeping  (ts-spec-011 §7)
# ---------------------------------------------------------------------------


def startup_cleanup(data_dir: Path) -> None:
    """Perform startup housekeeping.

    1. Delete all files in tmp/ (remnants of interrupted atomic writes).
    2. Scan transfers/ for stale state files (manifest missing on disk).
       Delete each stale state file and its tessera directory.
    3. Warn about orphaned tessera directories (no matching state file).
    """
    root = data_dir.expanduser()
    tmp = root / "tmp"
    manifests_dir = root / "manifests"
    tesserae_root = root / "tesserae"
    transfers_dir = root / "transfers"

    # Step 1: clean tmp/
    if tmp.exists():
        for f in tmp.iterdir():
            with contextlib.suppress(OSError):
                f.unlink()

    # Step 2: delete stale state files (missing manifest).
    if transfers_dir.exists():
        for state_file in transfers_dir.glob("*.state"):
            hash_hex = state_file.stem
            prefix = hash_hex[:2]
            mfile = manifests_dir / prefix / f"{hash_hex}.manifest"
            if not mfile.exists():
                log.info(
                    "Deleting stale state file (missing manifest): %s",
                    state_file,
                )
                state_file.unlink(missing_ok=True)
                td = tesserae_root / hash_hex
                if td.exists():
                    shutil.rmtree(td, ignore_errors=True)

    # Step 3: warn about orphaned tessera directories.
    if tesserae_root.exists():
        for tdir in tesserae_root.iterdir():
            if not tdir.is_dir():
                continue
            state_file = transfers_dir / f"{tdir.name}.state"
            if not state_file.exists():
                log.warning(
                    "Orphaned tessera directory (no state file): %s", tdir
                )
