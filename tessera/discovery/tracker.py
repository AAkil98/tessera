"""TrackerBackend — centralized HTTP tracker client.

Spec: ts-spec-007 §5

The tracker is a lightweight HTTP service that maps manifest hashes to
peer lists. This module is the client-side component.

Tracker API surface:
  POST /announce   {manifest_hash, agent_id, role}       → 200
  GET  /lookup     ?hash={manifest_hash_hex}             → 200 [{...}]
  POST /unannounce {manifest_hash, agent_id}             → 200
  GET  /health                                           → 200

httpx is an optional dependency ([tracker] extra). A mock client can be
injected for testing without installing httpx.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from tessera.discovery.backend import PeerRecord

log = logging.getLogger(__name__)

# Sentinel for the "httpx not installed" case.
try:
    import httpx as _httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]
    _HTTPX_AVAILABLE = False


class TrackerBackend:
    """HTTP tracker client (ts-spec-007 §5).

    Args:
        url: Tracker base URL (e.g. ``https://tracker.example.com``).
        name: Backend name used in PeerRecord.source (default "tracker").
        timeout: Per-request timeout in seconds (default 10).
        client: Injectable async HTTP client. If None, an httpx.AsyncClient
                is created automatically (requires httpx to be installed).
    """

    def __init__(
        self,
        url: str,
        name: str = "tracker",
        timeout: float = 10.0,
        client: Any = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._name = name
        self._timeout = timeout
        if client is not None:
            self._client = client
        elif _HTTPX_AVAILABLE:
            self._client = _httpx.AsyncClient(timeout=timeout)
        else:
            raise ImportError(
                "httpx is required for TrackerBackend. "
                "Install with: pip install 'tessera[tracker]'"
            )

    # ------------------------------------------------------------------
    # DiscoveryBackend interface
    # ------------------------------------------------------------------

    async def announce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
        role: Literal["seeder", "leecher"],
    ) -> None:
        """POST /announce — register this peer in the swarm."""
        try:
            resp = await self._client.post(
                f"{self._url}/announce",
                json={
                    "manifest_hash": manifest_hash.hex(),
                    "agent_id": agent_id.hex(),
                    "role": role,
                },
            )
            resp.raise_for_status()
        except Exception:
            log.warning("TrackerBackend.announce failed", exc_info=True)

    async def lookup(self, manifest_hash: bytes) -> list[PeerRecord]:
        """GET /lookup — return peers in the swarm."""
        try:
            resp = await self._client.get(
                f"{self._url}/lookup",
                params={"hash": manifest_hash.hex()},
            )
            resp.raise_for_status()
            peers: list[PeerRecord] = []
            for item in resp.json():
                peers.append(
                    PeerRecord(
                        agent_id=bytes.fromhex(item["agent_id"]),
                        role=item.get("role", "seeder"),
                        last_seen=float(item.get("last_seen", time.time())),
                        source=self._name,
                    )
                )
            return peers
        except Exception:
            log.warning("TrackerBackend.lookup failed", exc_info=True)
            return []

    async def unannounce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
    ) -> None:
        """POST /unannounce — remove this peer from the swarm listing."""
        try:
            resp = await self._client.post(
                f"{self._url}/unannounce",
                json={
                    "manifest_hash": manifest_hash.hex(),
                    "agent_id": agent_id.hex(),
                },
            )
            resp.raise_for_status()
        except Exception:
            log.warning("TrackerBackend.unannounce failed", exc_info=True)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if hasattr(self._client, "aclose"):
            await self._client.aclose()
