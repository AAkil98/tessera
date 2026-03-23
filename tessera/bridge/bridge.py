"""Intelligence Bridge — ts-spec-009 §2.

Central coordinator for all AI capabilities. Wraps a BaseAgentClient
(from madakit) and exposes adapter methods to the rest of the system.
All methods return fallback values immediately when inactive.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from tessera.bridge.sanitizer import SanitizationFilter

log = logging.getLogger(__name__)


@runtime_checkable
class BaseAgentClient(Protocol):
    """Minimal interface expected from a madakit agent client."""

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        ...


@dataclass
class SelectionHint:
    """Ordered tessera indices, highest priority first (ts-spec-009 §4)."""

    priority_indices: list[int]


@dataclass
class PeerRankingHint:
    """Ordered peer AgentIds with a confidence score (ts-spec-009 §5)."""

    tessera_index: int
    ranked_peers: list[bytes]
    confidence: float


class IntelligenceBridge:
    """Wraps an optional BaseAgentClient and exposes per-adapter helpers.

    If *client* is None, ``self.active`` is False and every method returns
    a safe fallback without performing any I/O.
    """

    def __init__(self, client: BaseAgentClient | None = None) -> None:
        self.client = client
        self.active: bool = client is not None
        self._sanitizer = SanitizationFilter()

        # Observability counters.
        self.calls_total: int = 0
        self.calls_failed: int = 0
        self.last_success: float | None = None
        self.last_failure: float | None = None
        self.last_failure_reason: str | None = None
        self.circuit_breaker_open: bool = False

    # ------------------------------------------------------------------
    # Core generate() with error tracking
    # ------------------------------------------------------------------

    async def _generate(self, prompt: str) -> str | None:
        """Call client.generate() and update observability counters."""
        if not self.active or self.client is None:
            return None
        self.calls_total += 1
        try:
            result = await self.client.generate(prompt)
            self.last_success = time.time()
            return result
        except Exception as exc:
            self.calls_failed += 1
            self.last_failure = time.time()
            self.last_failure_reason = str(exc)
            log.warning("IntelligenceBridge: generate() failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Discovery adapter entry point
    # ------------------------------------------------------------------

    async def discover(
        self,
        query: str,
        manifest_index: list[dict[str, Any]],
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Return ranked manifest-index entries matching *query*.

        Falls back to [] on any failure.
        """
        if not self.active:
            return []

        safe_query = self._sanitizer.sanitize(query)

        entries_text = "\n".join(
            f"- hash: {e['hash']}\n"
            f"  name: {self._sanitizer.sanitize(e.get('name', ''))}\n"
            f"  description: {self._sanitizer.sanitize(e.get('description', ''))}\n"
            f"  mime: {e.get('mime', '')}\n"
            f"  size: {e.get('size', 0)}"
            for e in manifest_index
        )

        prompt = (
            "System: You are a file search assistant. Given a user query and a list "
            "of available files with their metadata, return the manifest hashes of "
            "files that best match the query. Return results as a JSON array of "
            'objects with fields: manifest_hash (hex string), relevance_score '
            "(0.0-1.0), reason (brief explanation). Return an empty array if "
            "nothing matches.\n\n"
            f'User: Query: "{safe_query}"\n\nAvailable files:\n{entries_text}'
        )

        raw = await self._generate(prompt)
        if raw is None:
            return []

        try:
            results: list[dict[str, Any]] = json.loads(raw)
            if not isinstance(results, list):
                return []
            # Validate: keep only hashes present in the index.
            known = {e["hash"] for e in manifest_index}
            validated = [
                r for r in results
                if isinstance(r, dict) and r.get("manifest_hash") in known
            ]
            validated.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
            return validated[:max_results]
        except Exception as exc:
            log.warning("IntelligenceBridge: discover() parse failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Selection adapter entry point
    # ------------------------------------------------------------------

    async def get_selection_hint(
        self,
        name: str,
        mime_type: str,
        file_size: int,
        tessera_count: int,
        tessera_size: int,
    ) -> SelectionHint | None:
        """Return a one-shot priority ordering for tesserae, or None."""
        if not self.active:
            return None

        safe_name = self._sanitizer.sanitize(name)

        prompt = (
            "System: You are a file transfer optimizer. Given a file's metadata, "
            "suggest which byte regions should be fetched first for the best user "
            "experience. Return a JSON array of tessera index integers, highest "
            "priority first. Consider: file format headers, tables of contents, "
            "index structures, progressive rendering opportunities.\n\n"
            f"User: File: {safe_name}\n"
            f"MIME type: {mime_type}\n"
            f"Size: {file_size}\n"
            f"Tessera count: {tessera_count}\n"
            f"Tessera size: {tessera_size}"
        )

        raw = await self._generate(prompt)
        if raw is None:
            return None

        try:
            indices: list[int] = json.loads(raw)
            if not isinstance(indices, list):
                return None
            # Validate: keep only in-range integers.
            valid = [i for i in indices if isinstance(i, int) and 0 <= i < tessera_count]
            return SelectionHint(priority_indices=valid) if valid else None
        except Exception as exc:
            log.warning("IntelligenceBridge: get_selection_hint() parse failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Ranking adapter entry point
    # ------------------------------------------------------------------

    async def get_ranking_hint(
        self,
        tessera_index: int,
        peers: list[dict[str, Any]],
        transfer_name: str,
        progress_pct: float,
    ) -> PeerRankingHint | None:
        """Return a peer ordering hint for *tessera_index*, or None."""
        if not self.active:
            return None

        safe_name = self._sanitizer.sanitize(transfer_name)

        peers_text = "\n".join(
            f"- id: {p['id']}\n"
            f"  score: {p.get('score', 0.0)}\n"
            f"  latency_ms: {p.get('latency_ms', 0)}\n"
            f"  failure_rate: {p.get('failure_rate', 0.0)}\n"
            f"  bytes_delivered: {p.get('bytes_delivered', 0)}"
            for p in peers
        )

        prompt = (
            "System: You are a peer-to-peer transfer optimizer. Given a list of "
            "peers and their performance metrics, suggest an optimal preference "
            "ordering. Consider reliability, speed, and load distribution. Return a "
            'JSON object with fields: ranked_peers (array of agent_id hex strings '
            "in preferred order), confidence (0.0-1.0).\n\n"
            f"User: Transfer: {safe_name} ({progress_pct:.1f}% complete)\n"
            f"Peers:\n{peers_text}"
        )

        raw = await self._generate(prompt)
        if raw is None:
            return None

        try:
            obj: dict[str, Any] = json.loads(raw)
            if not isinstance(obj, dict):
                return None
            ranked_hex: list[str] = obj.get("ranked_peers", [])
            confidence: float = float(obj.get("confidence", 0.0))
            known_ids = {p["id"] for p in peers}
            valid_hex = [h for h in ranked_hex if isinstance(h, str) and h in known_ids]
            ranked_bytes = [bytes.fromhex(h) for h in valid_hex]
            return PeerRankingHint(
                tessera_index=tessera_index,
                ranked_peers=ranked_bytes,
                confidence=confidence,
            )
        except Exception as exc:
            log.warning("IntelligenceBridge: get_ranking_hint() parse failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Moderation adapter entry point
    # ------------------------------------------------------------------

    async def moderate_metadata(
        self, metadata: dict[str, str]
    ) -> tuple[bool, str, float]:
        """Return (allowed, reason, confidence).

        Falls back to (True, "", 1.0) when inactive or on failure.
        """
        if not self.active:
            return True, "", 1.0

        sanitized = self._sanitizer.sanitize_dict(metadata)

        meta_text = "\n".join(f"  {k}: {v}" for k, v in sanitized.items())
        prompt = (
            "System: You are a content safety classifier. Given file metadata, "
            "determine whether this file should be allowed on the network. Check for:"
            "\n- Malware indicators (suspicious filenames, known malware naming patterns)"
            "\n- Policy-violating content descriptions"
            "\n- Social engineering indicators"
            "\nReturn a JSON object with fields: allowed (boolean), reason (string), "
            "confidence (0.0-1.0).\n\n"
            f"User: File metadata:\n{meta_text}"
        )

        raw = await self._generate(prompt)
        if raw is None:
            return True, "", 1.0

        try:
            obj: dict[str, Any] = json.loads(raw)
            allowed: bool = bool(obj.get("allowed", True))
            reason: str = str(obj.get("reason", ""))
            confidence: float = float(obj.get("confidence", 1.0))
            return allowed, reason, confidence
        except Exception as exc:
            log.warning("IntelligenceBridge: moderate_metadata() parse failed: %s", exc)
            return True, "", 1.0
