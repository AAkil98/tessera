"""AI tests: RankingAdapter — ts-spec-009 §5."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tessera.bridge.bridge import IntelligenceBridge, PeerRankingHint
from tessera.bridge.ranking_adapter import RankingAdapter


class MockClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.call_count += 1
        return self._response


_PEERS = [
    {"id": "aabb", "score": 0.9, "latency_ms": 10, "failure_rate": 0.0, "bytes_delivered": 1000},
    {"id": "ccdd", "score": 0.5, "latency_ms": 50, "failure_rate": 0.1, "bytes_delivered": 500},
    {"id": "eeff", "score": 0.3, "latency_ms": 100, "failure_rate": 0.2, "bytes_delivered": 100},
]


def _make_adapter(response: str, interval: float = 60.0, threshold: float = 0.7) -> tuple[RankingAdapter, MockClient]:
    client = MockClient(response)
    bridge = IntelligenceBridge(client=client)
    return RankingAdapter(bridge, interval=interval, confidence_threshold=threshold), client


@pytest.mark.asyncio
async def test_ranking_hint_returned(tmp_path: None) -> None:
    """get_hint() returns a PeerRankingHint with valid data."""
    response = json.dumps({"ranked_peers": ["ccdd", "aabb", "eeff"], "confidence": 0.8})
    adapter, _ = _make_adapter(response)

    hint = await adapter.get_hint(0, _PEERS, "file.bin", 50.0)
    assert hint is not None
    assert hint.confidence == pytest.approx(0.8)
    assert bytes.fromhex("ccdd") in hint.ranked_peers


@pytest.mark.asyncio
async def test_ranking_hint_cached_within_interval(tmp_path: None) -> None:
    """A second call within the interval reuses the cached hint."""
    response = json.dumps({"ranked_peers": ["aabb"], "confidence": 0.9})
    adapter, client = _make_adapter(response, interval=3600.0)

    await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    await adapter.get_hint(1, _PEERS, "file.bin", 10.0)
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_ranking_rejects_unknown_peer_ids(tmp_path: None) -> None:
    """Peer IDs not in the peers list must be filtered out."""
    response = json.dumps({"ranked_peers": ["dead", "aabb"], "confidence": 0.9})
    adapter, _ = _make_adapter(response)

    hint = await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    assert hint is not None
    # "dead" is not in _PEERS so it must be absent.
    peer_hexes = [p.hex() for p in hint.ranked_peers]
    assert "dead" not in peer_hexes
    assert "aabb" in peer_hexes


@pytest.mark.asyncio
async def test_ranking_returns_none_when_inactive() -> None:
    """Without a client, get_hint() returns None."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge)
    hint = await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    assert hint is None


@pytest.mark.asyncio
async def test_ranking_returns_none_on_malformed_response() -> None:
    """Malformed JSON response → None."""
    adapter, _ = _make_adapter("not json")
    hint = await adapter.get_hint(0, _PEERS, "file.bin", 0.0)
    assert hint is None


def test_apply_high_confidence_hint_takes_precedence() -> None:
    """High-confidence hint ordering overrides score-ranked list."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa\xbb", b"\xcc\xdd", b"\xee\xff"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xcc\xdd", b"\xaa\xbb", b"\xee\xff"],
        confidence=0.9,
    )
    result = adapter.apply(score_ranked, hint)
    assert result[0] == b"\xcc\xdd"
    assert result[1] == b"\xaa\xbb"


def test_apply_no_hint_returns_score_ranked() -> None:
    """None hint → unmodified score-ranked list."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge)
    score_ranked = [b"\xaa", b"\xbb", b"\xcc"]
    assert adapter.apply(score_ranked, None) == score_ranked


def test_apply_low_confidence_moves_peers_forward() -> None:
    """Low-confidence hint gives a positional bonus without full reordering."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa", b"\xbb", b"\xcc", b"\xdd"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xdd"],
        confidence=0.5,  # below threshold
    )
    result = adapter.apply(score_ranked, hint)
    # \xdd should move forward from position 3.
    dd_idx = result.index(b"\xdd")
    assert dd_idx < 3
