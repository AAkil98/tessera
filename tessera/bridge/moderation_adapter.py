"""Moderation Adapter — ts-spec-009 §6.

Content safety gate for publish and fetch operations. Delegates to
IntelligenceBridge.moderate_metadata() and returns ModerationResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tessera.bridge.bridge import IntelligenceBridge


@dataclass
class ModerationResult:
    """Result of a moderation check (ts-spec-009 §6)."""

    allowed: bool
    reason: str = ""
    confidence: float = 1.0


class ModerationAdapter:
    """Run content moderation on manifest metadata."""

    def __init__(self, bridge: IntelligenceBridge) -> None:
        self._bridge = bridge

    async def check(self, metadata: dict[str, str]) -> ModerationResult:
        """Return a ModerationResult for the given metadata.

        When the bridge is inactive, always returns allowed=True.
        """
        allowed, reason, confidence = await self._bridge.moderate_metadata(metadata)
        return ModerationResult(allowed=allowed, reason=reason, confidence=confidence)
