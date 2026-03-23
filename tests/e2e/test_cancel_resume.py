"""E2E tests: cancel and resume — ts-spec-013 §5.3.

Cancel stops a transfer mid-way; resume picks up from the pieces already
on disk without re-downloading them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.errors import TesseraError
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


class PartialPeerSource:
    """Serve only the first *serve_count* pieces, then return None."""

    def __init__(
        self,
        ms: ManifestStore,
        ts: TesseraStore,
        mh: bytes,
        serve_count: int,
    ) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh
        self._serve_count = serve_count

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        if index < self._serve_count:
            return await self._ts.read(self._mh, index)
        return None


class LocalPeerSource:
    """Serve all pieces without restriction."""

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
async def test_cancel_transitions_swarm_to_closed(tmp_path: Path) -> None:
    """cancel() must transition the swarm to CLOSED without error."""
    from tessera.swarm.registry import SwarmState

    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(small())

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    leecher = TesseraNode(_config(fetch_dir))
    await leecher.start()

    src = LocalPeerSource(seeder._ms, seeder._ts, mh)
    leecher._test_piece_provider = src
    leecher._registry.create(mh, role="leecher")

    await leecher.cancel(mh)

    entry = leecher._registry.get(mh)
    assert entry.state == SwarmState.CLOSED

    await leecher.stop()


@pytest.mark.asyncio
async def test_resume_skips_already_downloaded_pieces(tmp_path: Path) -> None:
    """A second fetch() call skips pieces that are already on disk."""
    pub = tmp_path / "pub"
    pub.mkdir()
    data = small()
    (pub / "data.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    # First pass: only serve 2 of 4 pieces — fetch should fail.
    async with TesseraNode(_config(fetch_dir)) as leecher:
        partial = PartialPeerSource(seeder._ms, seeder._ts, mh, serve_count=2)
        leecher._test_piece_provider = partial
        with pytest.raises((TesseraError, Exception)):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

        # Verify pieces 0 and 1 landed on disk.
        assert leecher._ts.exists(mh, 0)
        assert leecher._ts.exists(mh, 1)
        assert not leecher._ts.exists(mh, 2)

    # Second pass: full source. Resume should only download pieces 2 and 3.
    pieces_fetched: list[int] = []

    class TrackingSource:
        async def get_manifest(self) -> bytes | None:
            return await seeder._ms.read(mh)

        async def get_piece(self, index: int) -> bytes | None:
            pieces_fetched.append(index)
            return await seeder._ts.read(mh, index)

    async with TesseraNode(_config(fetch_dir)) as leecher2:
        leecher2._test_piece_provider = TrackingSource()
        out = await leecher2.fetch(mh, output_path=fetch_dir / "out.bin")

    assert out.read_bytes() == data
    # Pieces 0 and 1 were already on disk — only 2 and 3 should have been fetched.
    assert 0 not in pieces_fetched
    assert 1 not in pieces_fetched
    assert 2 in pieces_fetched
    assert 3 in pieces_fetched


@pytest.mark.asyncio
async def test_resume_produces_correct_output(tmp_path: Path) -> None:
    """Full resume cycle: partial download + resume = correct assembled file."""
    pub = tmp_path / "pub"
    pub.mkdir()
    data = small()
    (pub / "data.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    # First attempt: serve only 1 piece.
    async with TesseraNode(_config(fetch_dir)) as leecher:
        partial = PartialPeerSource(seeder._ms, seeder._ts, mh, serve_count=1)
        leecher._test_piece_provider = partial
        with pytest.raises((TesseraError, Exception)):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

    # Resume: serve all pieces.
    async with TesseraNode(_config(fetch_dir)) as leecher2:
        full = LocalPeerSource(seeder._ms, seeder._ts, mh)
        leecher2._test_piece_provider = full
        out = await leecher2.fetch(mh, output_path=fetch_dir / "out.bin")

    assert out.read_bytes() == data


@pytest.mark.asyncio
async def test_progress_callback_not_called_for_resumed_pieces(
    tmp_path: Path,
) -> None:
    """on_progress must not fire for pieces skipped during resume."""
    pub = tmp_path / "pub"
    pub.mkdir()
    data = small()
    (pub / "data.bin").write_bytes(data)

    async with TesseraNode(_config(pub)) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()

    # Download pieces 0 and 1.
    async with TesseraNode(_config(fetch_dir)) as leecher:
        partial = PartialPeerSource(seeder._ms, seeder._ts, mh, serve_count=2)
        leecher._test_piece_provider = partial
        with pytest.raises((TesseraError, Exception)):
            await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

    # Resume — track which piece indices triggered progress callbacks.
    progress_indices: list[int] = []

    async with TesseraNode(_config(fetch_dir)) as leecher2:
        full = LocalPeerSource(seeder._ms, seeder._ts, mh)
        leecher2._test_piece_provider = full

        def on_progress(status: object) -> None:
            progress_indices.append(getattr(status, "pieces_done", -1))

        await leecher2.fetch(
            mh,
            output_path=fetch_dir / "out.bin",
            on_progress=on_progress,
        )

    # Only 2 progress callbacks (pieces 2 and 3).
    assert len(progress_indices) == 2
