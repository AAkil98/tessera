"""Discovery Adapter — ts-spec-009 §3.

Translates natural-language queries into manifest hash lookups using the
manifest index (local manifests known to this node).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tessera.types import DiscoveryResult

if TYPE_CHECKING:
    from tessera.bridge.bridge import IntelligenceBridge
    from tessera.storage.manifest_store import ManifestStore


class DiscoveryAdapter:
    """Wraps IntelligenceBridge.discover() and manages the manifest index."""

    def __init__(self, bridge: IntelligenceBridge, manifest_store: ManifestStore) -> None:
        self._bridge = bridge
        self._ms = manifest_store

    async def query(self, text: str, max_results: int = 10) -> list[DiscoveryResult]:
        """Search local manifests using a natural-language query.

        Returns an empty list when the bridge is inactive or on failure.
        """
        if not self._bridge.active:
            return []

        index = self._build_index()
        if not index:
            return []

        raw_results = await self._bridge.discover(text, index, max_results)

        results: list[DiscoveryResult] = []
        for r in raw_results:
            try:
                mh = bytes.fromhex(r["manifest_hash"])
                name = next(
                    (e["name"] for e in index if e["hash"] == r["manifest_hash"]), ""
                )
                results.append(
                    DiscoveryResult(
                        manifest_hash=mh,
                        name=str(name),
                        relevance_score=float(r.get("relevance_score", 0.0)),
                        metadata={"reason": str(r.get("reason", ""))},
                    )
                )
            except Exception:
                continue

        return results

    def _build_index(self) -> list[dict[str, Any]]:
        """Build a manifest index from the in-memory manifest store index."""
        index: list[dict[str, Any]] = []
        for mh, meta in self._ms.index.all_metadata():
            index.append(
                {
                    "hash": mh.hex(),
                    "name": meta.get("name", ""),
                    "description": meta.get("description", ""),
                    "mime": meta.get("mime", ""),
                    "size": 0,  # size not stored in index metadata
                }
            )
        return index
