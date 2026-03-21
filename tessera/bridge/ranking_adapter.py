"""Ranking Adapter — ts-spec-009 §5.

Provides periodic AI-driven peer ranking hints that augment the score-based
Peer Scorer. The hint is refreshed on a configurable interval.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tessera.bridge.bridge import IntelligenceBridge, PeerRankingHint


class RankingAdapter:
    """Cache and refresh PeerRankingHints on a configurable interval."""

    def __init__(
        self,
        bridge: IntelligenceBridge,
        interval: float = 60.0,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._bridge = bridge
        self._interval = interval
        self._threshold = confidence_threshold
        self._cache: PeerRankingHint | None = None
        self._last_refresh: float = 0.0

    async def get_hint(
        self,
        tessera_index: int,
        peers: list[dict[str, Any]],
        transfer_name: str,
        progress_pct: float,
    ) -> PeerRankingHint | None:
        """Return a cached or freshly fetched PeerRankingHint, or None."""
        if not self._bridge.active:
            return None

        now = time.monotonic()
        if self._cache is None or (now - self._last_refresh) >= self._interval:
            self._cache = await self._bridge.get_ranking_hint(
                tessera_index=tessera_index,
                peers=peers,
                transfer_name=transfer_name,
                progress_pct=progress_pct,
            )
            self._last_refresh = now

        return self._cache

    def apply(
        self,
        score_ranked: list[bytes],
        hint: PeerRankingHint | None,
    ) -> list[bytes]:
        """Merge *hint* with the score-ranked list per the spec blending rules."""
        if hint is None or not hint.ranked_peers:
            return score_ranked

        if hint.confidence >= self._threshold:
            # High confidence: hint ordering takes precedence.
            ordered = list(hint.ranked_peers)
            remainder = [p for p in score_ranked if p not in set(ordered)]
            return ordered + remainder
        else:
            # Low confidence: hint-preferred peers get a positional bonus.
            # Move them one position forward for each 0.1 confidence above 0.
            bonus = int(hint.confidence * 10)
            result = list(score_ranked)
            for peer in reversed(hint.ranked_peers):
                if peer in result:
                    idx = result.index(peer)
                    new_idx = max(0, idx - bonus)
                    result.insert(new_idx, result.pop(idx))
            return result
