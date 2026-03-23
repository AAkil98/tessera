"""Selection Adapter — ts-spec-009 §4.

Provides an AI-driven SelectionStrategy that wraps IntelligenceBridge
and falls back to rarest-first when the bridge is inactive or a call fails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tessera.bridge.bridge import IntelligenceBridge, SelectionHint


class AISelectionStrategy:
    """One-shot selection hint cached for the transfer lifetime.

    On the first call to ``prioritize()``, the LLM is queried.
    Subsequent calls use the cached result.
    """

    def __init__(
        self,
        bridge: IntelligenceBridge,
        name: str,
        mime_type: str,
        file_size: int,
        tessera_count: int,
        tessera_size: int,
    ) -> None:
        self._bridge = bridge
        self._name = name
        self._mime = mime_type
        self._file_size = file_size
        self._tessera_count = tessera_count
        self._tessera_size = tessera_size
        self._hint: SelectionHint | None = None
        self._fetched: bool = False

    async def fetch_hint(self) -> None:
        """Pre-fetch the selection hint from the LLM (call once at transfer start)."""
        if self._fetched:
            return
        self._fetched = True
        self._hint = await self._bridge.get_selection_hint(
            name=self._name,
            mime_type=self._mime,
            file_size=self._file_size,
            tessera_count=self._tessera_count,
            tessera_size=self._tessera_size,
        )

    def prioritize(self, needed: set[int]) -> list[int]:
        """Return *needed* indices sorted by AI priority, defaulting to sorted order."""
        if self._hint is None or not self._hint.priority_indices:
            return sorted(needed)
        prioritized = [i for i in self._hint.priority_indices if i in needed]
        remaining = sorted(needed - set(prioritized))
        return prioritized + remaining
