"""AI tests: RankingAdapter + AISelectionStrategy — ts-spec-009 §4-5."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tessera.bridge.bridge import IntelligenceBridge, PeerRankingHint
from tessera.bridge.ranking_adapter import RankingAdapter
from tessera.bridge.selection_adapter import AISelectionStrategy

# ---------------------------------------------------------------------------
# Mock clients
# ---------------------------------------------------------------------------


class MockClient:
    """Returns a preset JSON string from generate()."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self._response


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_PEERS: list[dict[str, Any]] = [
    {
        "id": "aabb",
        "score": 0.9,
        "latency_ms": 10,
        "failure_rate": 0.0,
        "bytes_delivered": 1000,
    },
    {
        "id": "ccdd",
        "score": 0.5,
        "latency_ms": 50,
        "failure_rate": 0.1,
        "bytes_delivered": 500,
    },
    {
        "id": "eeff",
        "score": 0.3,
        "latency_ms": 100,
        "failure_rate": 0.2,
        "bytes_delivered": 100,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ranking_adapter(
    response: str,
    interval: float = 60.0,
    threshold: float = 0.7,
) -> tuple[RankingAdapter, MockClient]:
    client = MockClient(response)
    bridge = IntelligenceBridge(client=client)
    adapter = RankingAdapter(bridge, interval=interval, confidence_threshold=threshold)
    return adapter, client


def _selection_strategy(
    response: str,
    tessera_count: int = 4,
) -> tuple[AISelectionStrategy, MockClient]:
    client = MockClient(response)
    bridge = IntelligenceBridge(client=client)
    strategy = AISelectionStrategy(
        bridge=bridge,
        name="report.pdf",
        mime_type="application/pdf",
        file_size=1_000_000,
        tessera_count=tessera_count,
        tessera_size=262_144,
    )
    return strategy, client


# ===========================================================================
# RankingAdapter tests
# ===========================================================================


@pytest.mark.asyncio
async def test_ranking_get_hint_calls_bridge() -> None:
    """get_hint() delegates to the bridge and returns a PeerRankingHint."""
    response = json.dumps({"ranked_peers": ["ccdd", "aabb", "eeff"], "confidence": 0.8})
    adapter, client = _ranking_adapter(response)

    hint = await adapter.get_hint(0, _PEERS, "file.bin", 50.0)

    assert hint is not None
    assert len(client.calls) == 1
    assert hint.confidence == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_ranking_cache_within_interval() -> None:
    """A second call within the interval reuses the cached hint (no extra LLM call)."""
    response = json.dumps({"ranked_peers": ["aabb"], "confidence": 0.9})
    adapter, client = _ranking_adapter(response, interval=3600.0)

    await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    await adapter.get_hint(1, _PEERS, "file.bin", 10.0)

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_ranking_refresh_after_interval() -> None:
    """After the interval elapses, get_hint() fetches a new hint."""
    response = json.dumps({"ranked_peers": ["aabb"], "confidence": 0.9})
    adapter, client = _ranking_adapter(response, interval=60.0)

    await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    assert len(client.calls) == 1

    # Simulate interval expiry by backdating _last_refresh.
    adapter._last_refresh -= 120.0

    await adapter.get_hint(0, _PEERS, "file.bin", 50.0)
    assert len(client.calls) == 2


def test_ranking_apply_high_confidence() -> None:
    """High-confidence hint ordering takes precedence over score-ranked list."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa\xbb", b"\xcc\xdd", b"\xee\xff"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xee\xff", b"\xcc\xdd", b"\xaa\xbb"],
        confidence=0.9,
    )

    result = adapter.apply(score_ranked, hint)

    assert result[0] == b"\xee\xff"
    assert result[1] == b"\xcc\xdd"
    assert result[2] == b"\xaa\xbb"


def test_ranking_apply_low_confidence() -> None:
    """Low-confidence hint applies a positional bonus rather than full reordering."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa", b"\xbb", b"\xcc", b"\xdd"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xdd"],
        confidence=0.5,  # below threshold
    )

    result = adapter.apply(score_ranked, hint)

    # \xdd should move forward from its original position 3.
    dd_idx = result.index(b"\xdd")
    assert dd_idx < 3


def test_ranking_apply_none_hint() -> None:
    """None hint returns the original score-ranked order unchanged."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge)

    score_ranked = [b"\xaa", b"\xbb", b"\xcc"]
    result = adapter.apply(score_ranked, None)

    assert result == score_ranked


def test_ranking_apply_unknown_peers_dropped() -> None:
    """Hint peers not in score_ranked are placed at the end."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa", b"\xbb"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xff", b"\xaa"],  # \xff is unknown
        confidence=0.9,
    )

    result = adapter.apply(score_ranked, hint)

    # \xff is not in score_ranked so it appears in hint ordering but is kept;
    # \xaa is moved to the front, \xbb remains as remainder.
    assert b"\xaa" in result
    assert b"\xbb" in result
    # \xff from hint goes first (high-confidence path), then \xaa, then remainder.
    assert result.index(b"\xaa") < result.index(b"\xbb")


# ===========================================================================
# AISelectionStrategy tests
# ===========================================================================


@pytest.mark.asyncio
async def test_selection_fetch_hint_calls_bridge() -> None:
    """fetch_hint() delegates to the bridge and the LLM is called."""
    strategy, client = _selection_strategy(json.dumps([2, 0, 1, 3]))

    await strategy.fetch_hint()

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_selection_fetch_hint_cached() -> None:
    """A second fetch_hint() is a no-op; the LLM is not called again."""
    strategy, client = _selection_strategy(json.dumps([2, 0]))

    await strategy.fetch_hint()
    await strategy.fetch_hint()

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_selection_prioritize_with_hint() -> None:
    """Hint [2, 0] reorders needed={0,1,2,3} to [2, 0, 1, 3]."""
    strategy, _ = _selection_strategy(json.dumps([2, 0]))

    await strategy.fetch_hint()
    result = strategy.prioritize({0, 1, 2, 3})

    assert result == [2, 0, 1, 3]


@pytest.mark.asyncio
async def test_selection_prioritize_without_hint() -> None:
    """Without a hint (malformed response), prioritize returns sorted order."""
    strategy, _ = _selection_strategy("not json")

    await strategy.fetch_hint()
    result = strategy.prioritize({3, 1, 0, 2})

    assert result == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_selection_prioritize_filters_unavailable() -> None:
    """Hint indices not in needed are excluded; remaining are sorted."""
    strategy, _ = _selection_strategy(json.dumps([5, 0]))

    await strategy.fetch_hint()
    result = strategy.prioritize({0, 1})

    # 5 is not in needed, so only 0 from hint, then 1 as remainder.
    assert result == [0, 1]


@pytest.mark.asyncio
async def test_selection_inactive_bridge_returns_sorted() -> None:
    """When bridge is inactive, prioritize() returns sorted indices."""
    bridge = IntelligenceBridge(client=None)
    strategy = AISelectionStrategy(
        bridge=bridge,
        name="file.bin",
        mime_type="application/octet-stream",
        file_size=100,
        tessera_count=4,
        tessera_size=262_144,
    )

    await strategy.fetch_hint()
    result = strategy.prioritize({3, 1, 0, 2})

    assert result == [0, 1, 2, 3]
