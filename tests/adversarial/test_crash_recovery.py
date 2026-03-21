"""Adversarial tests: crash recovery — ts-spec-013 §6.10."""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.storage.layout import startup_cleanup, tessera_path
from tests.fixtures import DEFAULT_CHUNK_SIZE, small

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


def _config(d: Path) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE)


@pytest.mark.adversarial
def test_crash_tmp_cleanup_on_startup(tmp_path: Path) -> None:
    """Orphan files in tmp/ are deleted on startup."""
    from tessera.storage.layout import ensure_data_dir

    data_dir = tmp_path / "node"
    ensure_data_dir(data_dir)

    # Plant orphan files.
    (data_dir / "tmp" / "orphan1.piece").write_bytes(b"garbage")
    (data_dir / "tmp" / "orphan2.state").write_bytes(b"garbage")

    startup_cleanup(data_dir)

    assert list((data_dir / "tmp").iterdir()) == []


@pytest.mark.adversarial
async def test_resume_after_partial_download(tmp_path: Path) -> None:
    """Restart after partial download resumes from existing pieces."""
    from tessera.storage.manifest_store import ManifestStore
    from tessera.storage.tessera_store import TesseraStore

    pub = tmp_path / "pub"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    # Partial fetch: manually write only pieces 0 and 1.
    fet = tmp_path / "fetcher"
    from tessera.storage.layout import ensure_data_dir

    ensure_data_dir(fet)
    ms = ManifestStore(fet)
    ts = TesseraStore(fet)

    assert publisher._manifest_store is not None
    assert publisher._tessera_store is not None
    raw = await publisher._manifest_store.read(mh)
    assert raw is not None
    await ms.write(raw)
    for i in range(2):  # only first 2 of 4 pieces
        data = await publisher._tessera_store.read(mh, i)
        assert data is not None
        await ts.write(mh, i, data)

    # Resume: fetch() should skip pieces 0-1 and get 2-3 from provider.
    class PartialSource:
        async def get_manifest(self) -> bytes | None:
            return await publisher._manifest_store.read(mh)  # type: ignore[union-attr]

        async def get_piece(self, index: int) -> bytes | None:
            return await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    fetcher_node = TesseraNode(_config(fet))
    await fetcher_node.start()
    fetcher_node._test_piece_provider = PartialSource()  # type: ignore[assignment]
    out = await fetcher_node.fetch(mh)
    await fetcher_node.stop()

    assert out.read_bytes() == small()


@pytest.mark.adversarial
async def test_corrupt_piece_detected_at_assembly(tmp_path: Path) -> None:
    """Piece corrupted on disk after write is caught at whole-file verify."""
    from tessera.errors import IntegrityError as TE_IntegrityError

    pub = tmp_path / "pub"
    src = pub / "small.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    async with TesseraNode(_config(pub)) as publisher:
        mh = await publisher.publish(str(src))

    # Corrupt piece 2 on disk in the publisher's store.
    p = tessera_path(pub, mh, 2)
    p.write_bytes(b"\xff" * TESSERA_SIZE)

    # The fetcher copies pieces directly — including the corrupt one.
    class DirectSource:
        async def get_manifest(self) -> bytes | None:
            return await publisher._manifest_store.read(mh)  # type: ignore[union-attr]

        async def get_piece(self, index: int) -> bytes | None:
            return p.read_bytes() if index == 2 else await publisher._tessera_store.read(mh, index)  # type: ignore[union-attr]

    fet = tmp_path / "fetcher"
    async with TesseraNode(_config(fet)) as fetcher:
        fetcher._test_piece_provider = DirectSource()  # type: ignore[assignment]
        with pytest.raises(TE_IntegrityError):
            await fetcher.fetch(mh)
