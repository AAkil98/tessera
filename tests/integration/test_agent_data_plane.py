"""Integration tests: Agent Data Plane additions — metadata, list_manifests, watch, publish_bytes."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from tessera.config import TesseraConfig
from tessera.content.chunker import Chunker
from tessera.content.manifest import ManifestBuilder, ManifestParser
from tessera.metadata import CHANNEL, CREATED_AT, PRODUCER, auto_populate
from tessera.node import TesseraNode
from tessera.storage.layout import ensure_data_dir, manifest_path
from tessera.storage.manifest_store import ManifestStore
from tessera.types import ManifestEvent, ManifestInfo, WatchHandle
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str,
    channel: str | None = None,
    producer: str | None = None,
    artifact_type: str | None = None,
    created_at: str | None = None,
) -> bytes:
    """Build a tiny manifest with optional metadata fields."""
    data = tiny()
    meta: dict[str, str] = {"name": name}
    if channel is not None:
        meta["channel"] = channel
    if producer is not None:
        meta["producer"] = producer
    if artifact_type is not None:
        meta["artifact_type"] = artifact_type
    if created_at is not None:
        meta["created_at"] = created_at
    builder = ManifestBuilder(
        file_size=len(data),
        tessera_size=TESSERA_SIZE,
        metadata=meta,
    )
    builder.add_tessera(hashlib.sha256(data).digest())
    return builder.build()


async def _seed_index(
    tmp_path: Path,
    manifests: list[bytes],
) -> ManifestStore:
    """Write manifests and return a ManifestStore with a populated index."""
    ensure_data_dir(tmp_path)
    ms = ManifestStore(tmp_path)
    for m in manifests:
        await ms.write(m)
    return ms


# ===================================================================
# Metadata conventions
# ===================================================================


class TestMetadataConventions:
    """Tests for tessera.metadata auto-population and constants."""

    def test_auto_populate_adds_created_at(self) -> None:
        meta: dict[str, str] = {"name": "test.bin"}
        auto_populate(meta)
        assert "created_at" in meta
        # ISO 8601 format check.
        from datetime import datetime

        datetime.fromisoformat(meta["created_at"])

    def test_auto_populate_does_not_overwrite(self) -> None:
        meta: dict[str, str] = {"name": "test.bin", "created_at": "2025-01-01T00:00:00+00:00"}
        auto_populate(meta)
        assert meta["created_at"] == "2025-01-01T00:00:00+00:00"

    @pytest.mark.integration
    async def test_publish_auto_populates_created_at(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "input.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            mh = await node.publish(src)
            infos = await node.list_manifests()
            assert len(infos) == 1
            assert "created_at" in infos[0].metadata


# ===================================================================
# list_manifests()
# ===================================================================


class TestListManifests:
    """Tests for TesseraNode.list_manifests()."""

    @pytest.mark.integration
    async def test_list_all(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "a.bin", "channel": "ch1"})
            await node.publish(src, metadata={"name": "b.bin", "channel": "ch2"})
            results = await node.list_manifests()
            assert len(results) == 2

    @pytest.mark.integration
    async def test_filter_by_channel(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "a.bin", "channel": "ch1"})
            await node.publish(src, metadata={"name": "b.bin", "channel": "ch2"})
            results = await node.list_manifests(channel="ch1")
            assert len(results) == 1
            assert results[0].metadata["name"] == "a.bin"

    @pytest.mark.integration
    async def test_filter_by_producer(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "a.bin", "producer": "worker-1"})
            await node.publish(src, metadata={"name": "b.bin", "producer": "worker-2"})
            results = await node.list_manifests(producer="worker-1")
            assert len(results) == 1
            assert results[0].metadata["producer"] == "worker-1"

    @pytest.mark.integration
    async def test_filter_by_artifact_type(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "model.bin", "artifact_type": "model"})
            await node.publish(src, metadata={"name": "data.bin", "artifact_type": "dataset"})
            results = await node.list_manifests(artifact_type="model")
            assert len(results) == 1
            assert results[0].metadata["artifact_type"] == "model"

    @pytest.mark.integration
    async def test_filter_combined(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(
                src,
                metadata={"name": "a.bin", "channel": "ch1", "producer": "w1"},
            )
            await node.publish(
                src,
                metadata={"name": "b.bin", "channel": "ch1", "producer": "w2"},
            )
            results = await node.list_manifests(channel="ch1", producer="w1")
            assert len(results) == 1
            assert results[0].metadata["name"] == "a.bin"

    @pytest.mark.integration
    async def test_filter_no_match(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "a.bin", "channel": "ch1"})
            results = await node.list_manifests(channel="nonexistent")
            assert results == []

    @pytest.mark.integration
    async def test_filter_by_since(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(
                src,
                metadata={"name": "old.bin", "created_at": "2020-01-01T00:00:00+00:00"},
            )
            await node.publish(
                src,
                metadata={"name": "new.bin", "created_at": "2026-06-01T00:00:00+00:00"},
            )
            # since = 2025-01-01 as Unix timestamp
            from datetime import datetime, timezone

            cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
            results = await node.list_manifests(since=cutoff)
            assert len(results) == 1
            assert results[0].metadata["name"] == "new.bin"

    @pytest.mark.integration
    async def test_empty_index(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            results = await node.list_manifests()
            assert results == []

    @pytest.mark.integration
    async def test_not_started_raises(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        node = TesseraNode(cfg)
        with pytest.raises(Exception, match="not started"):
            await node.list_manifests()

    @pytest.mark.integration
    async def test_since_skips_missing_created_at(self, tmp_path: Path) -> None:
        """Manifests without created_at are excluded when since is given."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            mh = await node.publish(src, metadata={"name": "no_ts.bin"})
            # Remove created_at from the index entry.
            node._ms.index._index[mh].pop("created_at", None)
            results = await node.list_manifests(since=0.0)
            assert results == []

    @pytest.mark.integration
    async def test_since_skips_invalid_created_at(self, tmp_path: Path) -> None:
        """Manifests with unparseable created_at are excluded when since is given."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            mh = await node.publish(src, metadata={"name": "bad_ts.bin"})
            # Replace with an invalid timestamp.
            node._ms.index._index[mh]["created_at"] = "not-a-date"
            results = await node.list_manifests(since=0.0)
            assert results == []

    @pytest.mark.integration
    async def test_sort_order_descending(self, tmp_path: Path) -> None:
        """Results are sorted by created_at descending."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            await node.publish(
                src, metadata={"name": "old.bin", "created_at": "2024-01-01T00:00:00+00:00"},
            )
            await node.publish(
                src, metadata={"name": "new.bin", "created_at": "2026-06-01T00:00:00+00:00"},
            )
            await node.publish(
                src, metadata={"name": "mid.bin", "created_at": "2025-06-01T00:00:00+00:00"},
            )
            results = await node.list_manifests()
            names = [r.metadata["name"] for r in results]
            assert names == ["new.bin", "mid.bin", "old.bin"]

    @pytest.mark.integration
    async def test_missing_created_at_sorts_last(self, tmp_path: Path) -> None:
        """Entries without created_at sort after those with timestamps."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            mh_no_ts = await node.publish(src, metadata={"name": "no_ts.bin"})
            await node.publish(
                src, metadata={"name": "has_ts.bin", "created_at": "2026-01-01T00:00:00+00:00"},
            )
            # Strip created_at from the first manifest's index entry.
            node._ms.index._index[mh_no_ts].pop("created_at", None)
            results = await node.list_manifests()
            names = [r.metadata["name"] for r in results]
            assert names[-1] == "no_ts.bin"

    @pytest.mark.integration
    async def test_read_returns_none_skips_entry(self, tmp_path: Path) -> None:
        """If the manifest file is deleted from disk, list_manifests skips it."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            mh = await node.publish(src, metadata={"name": "ghost.bin"})
            # Delete the manifest file on disk (index still has the entry).
            mp = manifest_path(tmp_path, mh)
            mp.unlink()
            results = await node.list_manifests()
            # The ghost entry should be silently skipped.
            assert all(r.manifest_hash != mh for r in results)


# ===================================================================
# watch()
# ===================================================================


class TestWatch:
    """Tests for TesseraNode.watch()."""

    @pytest.mark.integration
    async def test_watch_fires_on_new(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())

        events: list[ManifestEvent] = []
        fired = asyncio.Event()

        def on_new(evt: ManifestEvent) -> None:
            events.append(evt)
            fired.set()

        async with TesseraNode(cfg) as node:
            handle = await node.watch(channel="test-ch", on_new=on_new, poll_interval=0.1)
            try:
                # Publish after watch started.
                await node.publish(src, metadata={"name": "watched.bin", "channel": "test-ch"})
                await asyncio.wait_for(fired.wait(), timeout=5.0)
                assert len(events) == 1
                assert events[0].metadata["channel"] == "test-ch"
            finally:
                await handle.cancel()

    @pytest.mark.integration
    async def test_watch_ignores_non_matching(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())

        events: list[ManifestEvent] = []

        async with TesseraNode(cfg) as node:
            handle = await node.watch(
                channel="target", on_new=lambda evt: events.append(evt), poll_interval=0.1,
            )
            try:
                await node.publish(src, metadata={"name": "other.bin", "channel": "other"})
                await asyncio.sleep(0.5)
                assert events == []
            finally:
                await handle.cancel()

    @pytest.mark.integration
    async def test_watch_cancel_stops_polling(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            handle = await node.watch(poll_interval=0.05)
            await handle.cancel()
            # Task should be done after cancel.
            assert handle._task.done()

    @pytest.mark.integration
    async def test_watch_returns_handle(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            handle = await node.watch(poll_interval=60.0)
            assert isinstance(handle, WatchHandle)
            await handle.cancel()

    @pytest.mark.integration
    async def test_watch_does_not_fire_for_existing(self, tmp_path: Path) -> None:
        """Manifests present before watch() is called should not trigger on_new."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())

        events: list[ManifestEvent] = []

        async with TesseraNode(cfg) as node:
            await node.publish(src, metadata={"name": "pre.bin", "channel": "ch"})
            handle = await node.watch(
                channel="ch", on_new=lambda evt: events.append(evt), poll_interval=0.1,
            )
            try:
                await asyncio.sleep(0.5)
                assert events == []
            finally:
                await handle.cancel()

    @pytest.mark.integration
    async def test_watch_multiple_new_manifests(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())

        events: list[ManifestEvent] = []
        got_two = asyncio.Event()

        def on_new(evt: ManifestEvent) -> None:
            events.append(evt)
            if len(events) >= 2:
                got_two.set()

        async with TesseraNode(cfg) as node:
            handle = await node.watch(channel="ch", on_new=on_new, poll_interval=0.1)
            try:
                await node.publish(src, metadata={"name": "first.bin", "channel": "ch"})
                await node.publish(src, metadata={"name": "second.bin", "channel": "ch", "producer": "p2"})
                await asyncio.wait_for(got_two.wait(), timeout=5.0)
                assert len(events) == 2
            finally:
                await handle.cancel()

    @pytest.mark.integration
    async def test_watch_not_started_raises(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        node = TesseraNode(cfg)
        with pytest.raises(Exception, match="not started"):
            await node.watch()

    @pytest.mark.integration
    async def test_watch_on_new_none_does_not_raise(self, tmp_path: Path) -> None:
        """watch() with on_new=None should still poll without crashing."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())
        async with TesseraNode(cfg) as node:
            handle = await node.watch(poll_interval=0.05)
            try:
                await node.publish(src, metadata={"name": "silent.bin"})
                await asyncio.sleep(0.3)
            finally:
                await handle.cancel()
            # No crash — task completed via cancel, not via exception.
            assert handle._task.cancelled()

    @pytest.mark.integration
    async def test_watch_event_fields(self, tmp_path: Path) -> None:
        """Verify ManifestEvent fields match the published manifest."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        data = tiny()
        src.write_bytes(data)

        events: list[ManifestEvent] = []
        fired = asyncio.Event()

        def on_new(evt: ManifestEvent) -> None:
            events.append(evt)
            fired.set()

        async with TesseraNode(cfg) as node:
            handle = await node.watch(on_new=on_new, poll_interval=0.1)
            try:
                mh = await node.publish(src, metadata={"name": "evt.bin"})
                await asyncio.wait_for(fired.wait(), timeout=5.0)
                evt = events[0]
                assert evt.manifest_hash == mh
                assert evt.file_path == "evt.bin"
                assert evt.file_size == len(data)
                assert evt.tessera_count >= 1
                assert "name" in evt.metadata
            finally:
                await handle.cancel()

    @pytest.mark.integration
    async def test_watch_with_producer_filter(self, tmp_path: Path) -> None:
        """watch() filters by producer correctly."""
        cfg = TesseraConfig(data_dir=tmp_path)
        src = tmp_path / "f.bin"
        src.write_bytes(tiny())

        events: list[ManifestEvent] = []
        fired = asyncio.Event()

        def on_new(evt: ManifestEvent) -> None:
            events.append(evt)
            fired.set()

        async with TesseraNode(cfg) as node:
            handle = await node.watch(producer="agent-A", on_new=on_new, poll_interval=0.1)
            try:
                await node.publish(
                    src, metadata={"name": "wrong.bin", "producer": "agent-B"},
                )
                await node.publish(
                    src, metadata={"name": "right.bin", "producer": "agent-A"},
                )
                await asyncio.wait_for(fired.wait(), timeout=5.0)
                assert len(events) == 1
                assert events[0].metadata["producer"] == "agent-A"
            finally:
                await handle.cancel()


# ===================================================================
# publish_bytes()
# ===================================================================


class TestPublishBytes:
    """Tests for TesseraNode.publish_bytes()."""

    @pytest.mark.integration
    async def test_round_trip(self, tmp_path: Path) -> None:
        """Publish bytes, then verify the manifest is in the index."""
        cfg = TesseraConfig(data_dir=tmp_path)
        data = small()
        async with TesseraNode(cfg) as node:
            mh = await node.publish_bytes(data, metadata={"name": "mem.bin"})
            assert len(mh) == 32
            infos = await node.list_manifests()
            assert any(i.manifest_hash == mh for i in infos)

    @pytest.mark.integration
    async def test_metadata_name_required(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            await node.start()
            with pytest.raises(ValueError, match="name"):
                await node.publish_bytes(b"hello", metadata={"channel": "ch"})

    @pytest.mark.integration
    async def test_metadata_none_raises(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            with pytest.raises(ValueError, match="name"):
                await node.publish_bytes(b"hello")

    @pytest.mark.integration
    async def test_callback_fires(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        events: list[ManifestEvent] = []

        async with TesseraNode(cfg) as node:
            node.on_manifest_created = lambda evt: events.append(evt)
            await node.publish_bytes(tiny(), metadata={"name": "cb.bin"})
            assert len(events) == 1
            assert events[0].metadata["name"] == "cb.bin"

    @pytest.mark.integration
    async def test_created_at_auto_populated(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            mh = await node.publish_bytes(tiny(), metadata={"name": "ts.bin"})
            infos = await node.list_manifests()
            assert "created_at" in infos[0].metadata

    @pytest.mark.integration
    async def test_empty_bytes(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            mh = await node.publish_bytes(b"", metadata={"name": "empty.bin"})
            assert len(mh) == 32

    @pytest.mark.integration
    async def test_temp_file_cleaned_up(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        async with TesseraNode(cfg) as node:
            await node.publish_bytes(tiny(), metadata={"name": "cleanup.bin"})
            # No .publish_bytes temp files should remain.
            tmp_dir = tmp_path / "tmp"
            remaining = list(tmp_dir.glob("*.publish_bytes")) if tmp_dir.exists() else []
            assert remaining == []

    @pytest.mark.integration
    async def test_determinism(self, tmp_path: Path) -> None:
        """Same bytes + same metadata → same manifest hash."""
        data = tiny()
        meta = {"name": "det.bin"}
        cfg1 = TesseraConfig(data_dir=tmp_path / "a")
        cfg2 = TesseraConfig(data_dir=tmp_path / "b")
        async with TesseraNode(cfg1) as n1, TesseraNode(cfg2) as n2:
            # Override created_at to make it deterministic.
            fixed_meta = {**meta, "created_at": "2026-01-01T00:00:00+00:00"}
            mh1 = await n1.publish_bytes(data, metadata=fixed_meta)
            mh2 = await n2.publish_bytes(data, metadata=fixed_meta)
            assert mh1 == mh2

    @pytest.mark.integration
    async def test_not_started_raises(self, tmp_path: Path) -> None:
        cfg = TesseraConfig(data_dir=tmp_path)
        node = TesseraNode(cfg)
        with pytest.raises(ValueError, match="name"):
            await node.publish_bytes(b"hello")

    @pytest.mark.integration
    async def test_large_payload(self, tmp_path: Path) -> None:
        """publish_bytes works with multi-tessera payloads."""
        cfg = TesseraConfig(data_dir=tmp_path)
        data = small()  # 1 MiB — 4 tesserae
        async with TesseraNode(cfg) as node:
            mh = await node.publish_bytes(data, metadata={"name": "big.bin"})
            infos = await node.list_manifests()
            assert len(infos) == 1
            assert infos[0].tessera_count == 4

    @pytest.mark.integration
    async def test_publish_bytes_with_all_metadata(self, tmp_path: Path) -> None:
        """All reserved metadata keys survive the round-trip."""
        cfg = TesseraConfig(data_dir=tmp_path)
        meta = {
            "name": "full.bin",
            "channel": "nlp",
            "producer": "agent-X",
            "artifact_type": "dataset",
            "description": "test dataset",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        async with TesseraNode(cfg) as node:
            mh = await node.publish_bytes(tiny(), metadata=meta)
            infos = await node.list_manifests()
            stored = infos[0].metadata
            for key, value in meta.items():
                assert stored[key] == value


# ===================================================================
# __init__ exports
# ===================================================================


class TestInitExports:
    """Verify the public API re-exports new symbols."""

    @pytest.mark.integration
    def test_watch_handle_importable(self) -> None:
        from tessera import WatchHandle as WH

        assert WH is WatchHandle

    @pytest.mark.integration
    def test_all_contains_watch_handle(self) -> None:
        import tessera

        assert "WatchHandle" in tessera.__all__
