"""AI tests: AISelectionStrategy (Selection Adapter) — ts-spec-009 §4."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tessera.bridge.bridge import IntelligenceBridge
from tessera.bridge.selection_adapter import AISelectionStrategy


class MockClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.call_count += 1
        return self._response


def _make_strategy(
    response: str, tessera_count: int = 4
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


@pytest.mark.asyncio
async def test_selection_hint_reorders_needed(tmp_path: None) -> None:
    """AI priority indices come before the rest."""
    strategy, _ = _make_strategy(json.dumps([3, 0, 1, 2]))
    await strategy.fetch_hint()
    result = strategy.prioritize({0, 1, 2, 3})
    assert result[0] == 3
    assert result[1] == 0


@pytest.mark.asyncio
async def test_selection_hint_only_once(tmp_path: None) -> None:
    """The LLM is called exactly once regardless of how many times prioritize() runs."""
    strategy, client = _make_strategy(json.dumps([2, 0]))
    await strategy.fetch_hint()
    await strategy.fetch_hint()  # second call — should be no-op
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_selection_hint_filters_out_of_range(tmp_path: None) -> None:
    """Tessera indices outside [0, tessera_count) must be dropped."""
    strategy, _ = _make_strategy(
        json.dumps([99, 0, 2])
    )  # 99 is out of range for count=4
    await strategy.fetch_hint()
    result = strategy.prioritize({0, 1, 2, 3})
    assert 99 not in result
    assert result[0] == 0
    assert result[1] == 2


@pytest.mark.asyncio
async def test_selection_falls_back_to_sorted_on_inactive_bridge() -> None:
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


@pytest.mark.asyncio
async def test_selection_falls_back_on_malformed_response() -> None:
    """Malformed LLM response → no hint → sorted fallback."""
    strategy, _ = _make_strategy("not json")
    await strategy.fetch_hint()
    result = strategy.prioritize({0, 1, 2, 3})
    assert result == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_selection_only_returns_needed_indices() -> None:
    """prioritize() must only return indices from *needed*, not extras from the hint."""
    strategy, _ = _make_strategy(json.dumps([0, 1, 2, 3]))
    await strategy.fetch_hint()
    result = strategy.prioritize({1, 3})  # only 2 needed
    assert set(result) == {1, 3}
    assert len(result) == 2
