"""E2E tests: large file transfer — ts-spec-013 §5.4.

Uses the medium fixture (50 MiB, 200 tesserae) to verify that the full
pipeline scales correctly and that the assembled output matches the source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, medium

TESSERA_SIZE = DEFAULT_CHUNK_SIZE
MEDIUM_TESSERA_COUNT = 200


class LocalPeerSource:
    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts.read(self._mh, index)


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


@pytest.mark.asyncio
async def test_large_file_publish_and_fetch(tmp_path: Path) -> None:
    """50 MiB file publishes and fetches with a correct assembled output."""
    data = medium()
    pub = tmp_path / "pub"
    pub.mkdir()
    src_file = pub / "large.bin"
    src_file.write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(src_file)

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = LocalPeerSource(seeder._ms, seeder._ts, mh)
        out = await leecher.fetch(mh, output_path=fetch_dir / "large.bin")

    assert out.read_bytes() == data


@pytest.mark.asyncio
async def test_large_file_piece_count(tmp_path: Path) -> None:
    """A 50 MiB file with 256 KiB chunks produces exactly 200 tesserae."""
    from tessera.content.manifest import ManifestParser

    data = medium()
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "large.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "large.bin")
        raw = await seeder._ms.read(mh)

    info = ManifestParser.parse(raw, trusted_hash=mh)
    assert info.tessera_count == MEDIUM_TESSERA_COUNT


@pytest.mark.asyncio
async def test_large_file_progress_callback(tmp_path: Path) -> None:
    """Progress callback fires for every piece of a large file."""
    data = medium()
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "large.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "large.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    progress_calls: list[int] = []

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = LocalPeerSource(seeder._ms, seeder._ts, mh)

        def on_progress(status: object) -> None:
            progress_calls.append(getattr(status, "tesserae_verified", 0))

        await leecher.fetch(
            mh,
            output_path=fetch_dir / "large.bin",
            on_progress=on_progress,
        )

    assert len(progress_calls) == MEDIUM_TESSERA_COUNT
    assert progress_calls[-1] == MEDIUM_TESSERA_COUNT


@pytest.mark.asyncio
async def test_large_file_transfer_complete_callback(tmp_path: Path) -> None:
    """on_transfer_complete fires once with correct metadata after a large transfer."""
    data = medium()
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "large.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "large.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    events: list[object] = []

    async with TesseraNode(_config(fetch_dir)) as leecher:
        leecher._test_piece_provider = LocalPeerSource(seeder._ms, seeder._ts, mh)
        leecher.on_transfer_complete = events.append
        await leecher.fetch(mh, output_path=fetch_dir / "large.bin")

    assert len(events) == 1
    ev = events[0]
    assert getattr(ev, "file_size", 0) == len(data)
    assert getattr(ev, "manifest_hash", None) == mh
