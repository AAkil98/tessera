"""Adversarial tests: piece poisoning extended (T1) -- ts-spec-013 section 6.1.

Additional scenarios beyond test_piece_poisoning.py:
  - All pieces corrupted: IntegrityError on piece 0
  - Targeted corruption: only piece 2 of 4 is corrupted
  - Correct-size wrong-content: piece length matches but bytes differ
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import IntegrityError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


# ---------------------------------------------------------------------------
# Custom PieceSource classes
# ---------------------------------------------------------------------------


class AllCorruptSource:
    """Serve a valid manifest but corrupt every single piece."""

    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data is None:
            return None
        return bytes(b ^ 0xFF for b in data)


class TargetedCorruptSource:
    """Corrupt only one specific piece index; all others are honest."""

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        target_index: int,
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._target = target_index

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data is None:
            return None
        if index == self._target:
            return bytes(b ^ 0xFF for b in data)
        return data


class CorrectSizeWrongContentSource:
    """Return a piece of the correct length but filled with wrong bytes."""

    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        data = await self._ts.read(self._mh, index)
        if data is None:
            return None
        # Same length, completely different content.
        return b"\x00" * len(data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.adversarial
async def test_poison_all_pieces_fails_on_first(tmp_path: Path) -> None:
    """All pieces corrupted: IntegrityError raised on piece 0."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    provider = AllCorruptSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,  # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(IntegrityError) as exc_info:
            await fetcher.fetch(mh)

    err = exc_info.value
    assert err.manifest_hash == mh
    assert len(err.expected) == 32
    assert len(err.actual) == 32
    assert err.expected != err.actual


@pytest.mark.adversarial
async def test_poison_specific_index(tmp_path: Path) -> None:
    """Only piece 2 of 4 is corrupted; IntegrityError carries correct hashes."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    # small() = 4 chunks
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    provider = TargetedCorruptSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,  # type: ignore[arg-type]
        mh,
        target_index=2,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(IntegrityError) as exc_info:
            await fetcher.fetch(mh)

    err = exc_info.value
    assert err.manifest_hash == mh
    # expected and actual should both be 32-byte SHA-256 digests
    assert len(err.expected) == 32
    assert len(err.actual) == 32
    assert err.expected != err.actual


@pytest.mark.adversarial
async def test_poison_correct_size_wrong_content(tmp_path: Path) -> None:
    """Piece has the correct length but wrong bytes -- still caught."""
    pub = tmp_path / "pub"
    src = pub / "f.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    provider = CorrectSizeWrongContentSource(
        publisher._manifest_store,  # type: ignore[arg-type]
        publisher._tessera_store,  # type: ignore[arg-type]
        mh,
    )

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = provider  # type: ignore[assignment]
        with pytest.raises(IntegrityError) as exc_info:
            await fetcher.fetch(mh)

    err = exc_info.value
    assert err.manifest_hash == mh
    assert err.expected != err.actual
