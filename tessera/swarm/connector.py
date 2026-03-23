"""Peer Connector — admission sequence and eviction logic.

Spec: ts-spec-007 §3

7-step admission sequence:
  1. Capacity check (Capacity Enforcer)
  2. Blocklist check
  3. Channel establishment (MFP)
  4. HANDSHAKE exchange + validation
  5. Manifest exchange (if fetcher doesn't have it)
  6. BITFIELD exchange
  7. Register in SwarmRegistry + notify Transfer Engine

The MFP boundary is abstracted via MFPHandle so the connector is
testable without a live MFP agent (ts-spec-004 §6, MFP boundary).
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from tessera.errors import MessageError
from tessera.swarm.registry import PeerInfo, SwarmRegistry
from tessera.transfer.scorer import PeerScorer
from tessera.wire import errors as werr
from tessera.wire.messages import (
    PROTOCOL_VERSION,
    BitfieldMsg,
    Handshake,
    Message,
    encode,
)
from tessera.wire.state_machine import PeerSession

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MFP handle abstraction (ts-spec-004 §6)
# ---------------------------------------------------------------------------


@runtime_checkable
class MFPHandle(Protocol):
    """Minimal MFP API surface required by the Peer Connector.

    The full MFP agent exposes more methods; the connector only uses
    these three. This Protocol makes the connector testable without
    importing pymfp.
    """

    async def establish_channel(self, peer_agent_id: bytes) -> bytes:
        """Establish a bilateral channel. Returns the channel_id."""
        ...

    async def send(self, channel_id: bytes, payload: bytes) -> None:
        """Send a Tessera message payload over *channel_id*."""
        ...

    async def close_channel(self, channel_id: bytes) -> None:
        """Close *channel_id* and release resources."""
        ...


# ---------------------------------------------------------------------------
# AdmissionResult
# ---------------------------------------------------------------------------


@dataclass
class AdmissionResult:
    """Outcome of a peer admission attempt."""

    success: bool
    peer_info: PeerInfo | None = None
    reject_code: int | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# PeerConnector
# ---------------------------------------------------------------------------


class PeerConnector:
    """Manage peer admission and eviction for all swarms on this node.

    Args:
        mfp: MFP handle (real or mock) for channel operations.
        registry: Swarm Registry to query/update.
        scorer: Peer Scorer to initialise on admission and update on eviction.
        max_peers_per_swarm: Hard admission limit.
        eviction_threshold: Score below which peers can be displaced.
    """

    def __init__(
        self,
        mfp: MFPHandle,
        registry: SwarmRegistry,
        scorer: PeerScorer,
        max_peers_per_swarm: int = 50,
        eviction_threshold: float = 0.2,
    ) -> None:
        self._mfp = mfp
        self._registry = registry
        self._scorer = scorer
        self._max_peers = max_peers_per_swarm
        self._eviction_threshold = eviction_threshold
        # Per-peer session state machines: channel_id → PeerSession
        self._sessions: dict[bytes, PeerSession] = {}

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    async def admit(
        self,
        manifest_hash: bytes,
        peer_agent_id: bytes,
        local_bitfield_bytes: bytes,
        tessera_count: int,
        low_trust: bool = False,
    ) -> AdmissionResult:
        """Execute the 7-step admission sequence.

        Args:
            manifest_hash: Swarm identifier.
            peer_agent_id: Remote peer's MFP AgentId.
            local_bitfield_bytes: Our current bitfield to send in BITFIELD.
            tessera_count: Total tesserae (for HANDSHAKE tessera_count field).
            low_trust: If True, peer starts with lower initial Peer Scorer score.

        Returns:
            AdmissionResult with success=True on full admission.
        """
        # Step 1: Capacity check.
        try:
            entry = self._registry.get(manifest_hash)
        except Exception:
            return AdmissionResult(
                success=False, reason="swarm not found"
            )

        if len(entry.peers) >= self._max_peers:
            return AdmissionResult(
                success=False,
                reject_code=werr.SWARM_FULL,
                reason="swarm at capacity",
            )

        # Step 2: Blocklist check.
        if self._registry.is_blocklisted(manifest_hash, peer_agent_id):
            return AdmissionResult(
                success=False,
                reject_code=werr.SWARM_FULL,
                reason="peer is blocklisted",
            )

        # Step 3: Channel establishment.
        try:
            channel_id = await self._mfp.establish_channel(peer_agent_id)
        except Exception:
            log.debug(
                "Channel establishment failed for %s",
                peer_agent_id[:4].hex(),
                exc_info=True,
            )
            return AdmissionResult(
                success=False, reason="channel establishment failed"
            )

        # Create session state machine.
        session = PeerSession(peer_id=peer_agent_id)
        self._sessions[channel_id] = session

        # Step 4: HANDSHAKE exchange.
        try:
            hs_payload = encode(
                Handshake(
                    version=PROTOCOL_VERSION,
                    manifest_hash=manifest_hash,
                    tessera_count=tessera_count,
                    tessera_size=262_144,
                )
            )
            session.on_send(
                Handshake(
                    version=PROTOCOL_VERSION,
                    manifest_hash=manifest_hash,
                    tessera_count=tessera_count,
                    tessera_size=262_144,
                )
            )
            await self._mfp.send(channel_id, hs_payload)
        except Exception:
            await self._cleanup_channel(channel_id)
            return AdmissionResult(success=False, reason="HANDSHAKE send failed")

        # Steps 5-6 would require receiving the remote HANDSHAKE and BITFIELD
        # over the MFP channel. In the real swarm loop (Phase 6), an incoming
        # message dispatcher calls on_receive() and drives the session forward.
        # Here we complete the remaining registration steps.

        # Step 6: Send our BITFIELD.
        try:
            bf_payload = encode(BitfieldMsg(bitfield_bytes=local_bitfield_bytes))
            session.on_send(BitfieldMsg(bitfield_bytes=local_bitfield_bytes))
            await self._mfp.send(channel_id, bf_payload)
        except Exception:
            await self._cleanup_channel(channel_id)
            return AdmissionResult(success=False, reason="BITFIELD send failed")

        # Step 7: Register in registry + initialise scorer.
        peer_info = PeerInfo(
            agent_id=peer_agent_id,
            channel_id=channel_id,
            role="seeder",
        )
        self._registry.add_peer(manifest_hash, peer_info)
        self._scorer.add_peer(peer_agent_id, low_trust=low_trust)

        return AdmissionResult(success=True, peer_info=peer_info)

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def on_receive(
        self, manifest_hash: bytes, channel_id: bytes, msg: Message
    ) -> None:
        """Validate an incoming message against the session state machine.

        Raises MessageError on protocol violations so the caller can send
        REJECT and evict the peer.
        """
        session = self._sessions.get(channel_id)
        if session is None:
            raise MessageError(b"", werr.UNEXPECTED_MSG, "no session for channel")
        session.on_receive(msg)

    # ------------------------------------------------------------------
    # Eviction
    # ------------------------------------------------------------------

    async def evict(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
        *,
        reason: str = "",
        blocklist: bool = False,
    ) -> None:
        """Remove a peer from the swarm and close its channel.

        Args:
            blocklist: If True, add the peer to the per-swarm blocklist.
        """
        peer_info = self._registry.remove_peer(manifest_hash, agent_id)
        if peer_info is not None:
            log.debug(
                "Evicting peer %s from swarm %s: %s",
                agent_id[:4].hex(),
                manifest_hash[:4].hex(),
                reason,
            )
            # Clean up session and channel.
            self._sessions.pop(peer_info.channel_id, None)
            await self._cleanup_channel(peer_info.channel_id)

        if blocklist:
            self._registry.blocklist_peer(manifest_hash, agent_id)

        # Remove from scorer.
        if self._scorer.has_peer(agent_id):
            self._scorer.remove_peer(agent_id)

    def should_evict_for_score(self, agent_id: bytes) -> bool:
        """Return True if the peer's score is below the eviction hard floor."""
        if not self._scorer.has_peer(agent_id):
            return False
        return self._scorer.should_evict(agent_id)

    def candidate_for_displacement(
        self, manifest_hash: bytes
    ) -> bytes | None:
        """Return the lowest-scoring peer below eviction_threshold, or None."""
        entry = self._registry.get(manifest_hash)
        eligible = [
            pid
            for pid in entry.peers
            if self._scorer.has_peer(pid)
            and self._scorer.score(pid) < self._eviction_threshold
        ]
        if not eligible:
            return None
        return min(eligible, key=lambda pid: self._scorer.score(pid))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _cleanup_channel(self, channel_id: bytes) -> None:
        with contextlib.suppress(Exception):
            await self._mfp.close_channel(channel_id)
