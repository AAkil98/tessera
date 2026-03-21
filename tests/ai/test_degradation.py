"""AI tests: graceful degradation — ts-spec-009 §8.

When AI is unavailable (no client, failing client, malformed responses),
all transfers must proceed normally using fallback behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.bridge.bridge import IntelligenceBridge
from tessera.bridge.discovery_adapter import DiscoveryAdapter
from tessera.bridge.moderation_adapter import ModerationAdapter
from tessera.bridge.ranking_adapter import RankingAdapter
from tessera.bridge.selection_adapter import AISelectionStrategy
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


class FailingClient:
    """Always raises RuntimeError to simulate provider outage."""

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        raise RuntimeError("LLM provider unreachable")


class LocalPeerSource:
    def __init__(self, ms: ManifestStore, ts: TesseraStore, mh: bytes) -> None:
        self._ms = ms
        self._ts = ts
        self._mh = mh

    async def get_manifest(self) -> bytes | None:
        return await self._ms.read(self._mh)

    async def get_piece(self, index: int) -> bytes | None:
        return await self._ts.read(self._mh, index)


def _config(d: Path, client: Any = None) -> TesseraConfig:
    return TesseraConfig(data_dir=d, tessera_size=TESSERA_SIZE, ai_client=client)


# ---------------------------------------------------------------------------
# Bridge-level degradation
# ---------------------------------------------------------------------------

def test_bridge_inactive_without_client() -> None:
    """IntelligenceBridge.active must be False when no client is provided."""
    bridge = IntelligenceBridge(client=None)
    assert bridge.active is False


def test_bridge_active_with_client() -> None:
    """IntelligenceBridge.active must be True when a client is provided."""
    bridge = IntelligenceBridge(client=FailingClient())
    assert bridge.active is True


@pytest.mark.asyncio
async def test_bridge_tracks_failed_calls() -> None:
    """After a failing call, calls_failed is incremented."""
    bridge = IntelligenceBridge(client=FailingClient())
    result = await bridge._generate("test prompt")
    assert result is None
    assert bridge.calls_failed == 1
    assert bridge.last_failure is not None


@pytest.mark.asyncio
async def test_discovery_returns_empty_on_provider_failure() -> None:
    """Discovery returns [] when the LLM provider raises."""
    bridge = IntelligenceBridge(client=FailingClient())

    class FakeMS:
        class index:
            @staticmethod
            def all_metadata() -> list[tuple[bytes, dict[str, str]]]:
                return [(b"\x00" * 32, {"name": "test"})]

    adapter = DiscoveryAdapter(bridge, FakeMS())  # type: ignore[arg-type]
    results = await adapter.query("anything")
    assert results == []


@pytest.mark.asyncio
async def test_moderation_allows_all_on_provider_failure() -> None:
    """Moderation fails open when LLM provider raises."""
    bridge = IntelligenceBridge(client=FailingClient())
    adapter = ModerationAdapter(bridge)
    result = await adapter.check({"name": "suspicious.exe"})
    assert result.allowed is True


@pytest.mark.asyncio
async def test_selection_falls_back_on_provider_failure() -> None:
    """Selection hint is None when LLM provider raises; sorted order used."""
    bridge = IntelligenceBridge(client=FailingClient())
    strategy = AISelectionStrategy(
        bridge=bridge,
        name="file.bin",
        mime_type="application/octet-stream",
        file_size=100,
        tessera_count=4,
        tessera_size=TESSERA_SIZE,
    )
    await strategy.fetch_hint()
    result = strategy.prioritize({3, 1, 0, 2})
    assert result == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_ranking_returns_none_on_provider_failure() -> None:
    """Ranking returns None when LLM provider raises."""
    bridge = IntelligenceBridge(client=FailingClient())
    adapter = RankingAdapter(bridge)
    peers = [{"id": "aabb", "score": 0.9, "latency_ms": 10, "failure_rate": 0.0, "bytes_delivered": 0}]
    hint = await adapter.get_hint(0, peers, "file.bin", 0.0)
    assert hint is None


# ---------------------------------------------------------------------------
# Node-level degradation: full transfer still completes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transfer_succeeds_with_failing_ai_client(tmp_path: Path) -> None:
    """A complete publish→fetch cycle works even when the AI client always fails."""
    data = small()
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(data)

    # Publish with a failing AI client.
    async with TesseraNode(_config(pub, client=FailingClient())) as seeder:
        mh = await seeder.publish(pub / "data.bin")

    # Fetch with a failing AI client.
    fetch_dir = tmp_path / "fetch"
    fetch_dir.mkdir()
    async with TesseraNode(_config(fetch_dir, client=FailingClient())) as leecher:
        leecher._test_piece_provider = LocalPeerSource(seeder._ms, seeder._ts, mh)
        out = await leecher.fetch(mh, output_path=fetch_dir / "out.bin")

    assert out.read_bytes() == data


@pytest.mark.asyncio
async def test_node_status_includes_ai_status(tmp_path: Path) -> None:
    """status() includes AIStatus with active=True when a client is configured."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(tiny())

    async with TesseraNode(_config(pub, client=FailingClient())) as node:
        status = await node.status()

    from tessera.types import NodeStatus
    assert isinstance(status, NodeStatus)
    assert status.ai is not None
    assert status.ai.active is True


@pytest.mark.asyncio
async def test_node_status_ai_inactive_without_client(tmp_path: Path) -> None:
    """status() includes AIStatus with active=False when no client is configured."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(tiny())

    async with TesseraNode(_config(pub)) as node:
        status = await node.status()

    from tessera.types import NodeStatus
    assert isinstance(status, NodeStatus)
    assert status.ai is not None
    assert status.ai.active is False


@pytest.mark.asyncio
async def test_query_returns_empty_without_ai_client(tmp_path: Path) -> None:
    """query() returns [] when no AI client is configured."""
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "data.bin").write_bytes(tiny())

    async with TesseraNode(_config(pub)) as node:
        await node.publish(pub / "data.bin", metadata={"name": "Q3 Report"})
        results = await node.query("quarterly revenue")

    assert results == []
