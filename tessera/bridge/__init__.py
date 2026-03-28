"""Intelligence Bridge — ts-spec-009.

Public exports for the bridge package.
"""

from tessera.bridge.bridge import (
    BaseAgentClient,
    IntelligenceBridge,
    PeerRankingHint,
    SelectionHint,
)
from tessera.bridge.discovery_adapter import DiscoveryAdapter
from tessera.bridge.moderation_adapter import ModerationAdapter, ModerationResult
from tessera.bridge.ranking_adapter import RankingAdapter
from tessera.bridge.sanitizer import SanitizationFilter
from tessera.bridge.selection_adapter import AISelectionStrategy

__all__ = [
    "BaseAgentClient",
    "IntelligenceBridge",
    "PeerRankingHint",
    "SelectionHint",
    "DiscoveryAdapter",
    "ModerationAdapter",
    "ModerationResult",
    "RankingAdapter",
    "SanitizationFilter",
    "AISelectionStrategy",
]
