"""TesseraNode — the primary public entry point.

Spec: ts-spec-010 §2

Exposes five async methods:
  publish(file_path)  → manifest_hash
  fetch(manifest_hash) → output_path
  status([manifest_hash]) → TransferStatus | NodeStatus
  cancel(manifest_hash)
  query(text) → list[DiscoveryResult]

Piece transfer is abstracted behind the _PieceSource protocol so the
node can be exercised in-process (E2E tests) without a live MFP runtime.
Inject a PieceSource via  node._test_piece_provider = LocalPeerSource(...)
before calling fetch().  This attribute is not part of the public API.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from tessera.bridge.bridge import IntelligenceBridge
from tessera.bridge.discovery_adapter import DiscoveryAdapter
from tessera.bridge.moderation_adapter import ModerationAdapter
from tessera.content.bitfield import Bitfield
from tessera.content.chunker import Chunker
from tessera.content.manifest import ManifestBuilder, ManifestParser
from tessera.discovery.client import DiscoveryClient
from tessera.errors import CapacityError, IntegrityError, StarvationError, TesseraError
from tessera.storage.layout import ensure_data_dir, startup_cleanup
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.state import TransferState, write_state
from tessera.storage.tessera_store import TesseraStore
from tessera.swarm.capacity import CapacityEnforcer
from tessera.swarm.registry import SwarmRegistry
from tessera.transfer.assembler import Assembler
from tessera.transfer.scorer import PeerScorer
from tessera.transfer.verifier import PieceVerifier
from tessera.types import (
    AIStatus,
    DiscoveryResult,
    ManifestEvent,
    ManifestInfo,
    NodeStatus,
    SwarmState,
    TransferCompleteEvent,
    TransferMode,
    TransferStatus,
)

# ---------------------------------------------------------------------------
# Internal piece-source protocol (test injection point)
# ---------------------------------------------------------------------------


class _PieceSource(Protocol):
    """Abstraction over peer communication for piece transfer.

    In production this wraps the Swarm/MFP layer.
    In tests it wraps another TesseraNode's storage directly.
    """

    async def get_manifest(self) -> bytes | None:
        """Return raw manifest bytes, or None if unavailable."""
        ...

    async def get_piece(self, index: int) -> bytes | None:
        """Return raw piece bytes for *index*, or None if unavailable."""
        ...


# ---------------------------------------------------------------------------
# TesseraNode
# ---------------------------------------------------------------------------


class TesseraNode:
    """A Tessera node — manages publish, fetch, and swarm participation.

    Args:
        config: Node configuration. If None, all defaults are used.
    """

    def __init__(self, config: Any | None = None) -> None:
        # Import here to avoid circular imports during config validation.
        from tessera.config import TesseraConfig

        self._config: TesseraConfig = config or TesseraConfig()
        self._started = False

        # Storage (initialised in start()).
        self._data_dir: Path | None = None
        self._manifest_store: ManifestStore | None = None
        self._tessera_store: TesseraStore | None = None

        # Swarm components.
        self._registry = SwarmRegistry()
        self._scorer = PeerScorer(
            w_latency=self._config.score_weight_latency,
            w_failure=self._config.score_weight_failure,
            w_throughput=self._config.score_weight_throughput,
            penalty_mismatch=self._config.score_penalty_mismatch,
            min_peer_score=self._config.score_min,
            eviction_threshold=self._config.eviction_threshold,
            deprioritize_threshold=self._config.score_deprioritize,
        )
        self._capacity = CapacityEnforcer(
            max_peers_per_swarm=self._config.max_peers_per_swarm,
            max_swarms_per_node=self._config.max_swarms_per_node,
        )
        self._discovery: DiscoveryClient | None = None

        # Public event callbacks (ts-spec-010 §6).
        self.on_manifest_created: Callable[[ManifestEvent], None] | None = None
        self.on_manifest_received: Callable[[ManifestEvent], None] | None = None
        self.on_transfer_complete: Callable[[TransferCompleteEvent], None] | None = None

        # Test-only injection point — not part of the public API.
        self._test_piece_provider: _PieceSource | None = None

        # Intelligence Bridge (ts-spec-009).
        self._bridge = IntelligenceBridge(client=self._config.ai_client)
        self._discovery_adapter: DiscoveryAdapter | None = None
        self._moderation_adapter = ModerationAdapter(self._bridge)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize storage, run startup cleanup, rebuild manifest index."""
        data_dir = self._config.data_dir.expanduser()
        ensure_data_dir(data_dir)
        startup_cleanup(data_dir)
        self._data_dir = data_dir
        self._manifest_store = ManifestStore(data_dir)
        self._discovery_adapter = DiscoveryAdapter(self._bridge, self._manifest_store)
        self._tessera_store = TesseraStore(data_dir)
        await self._manifest_store.rebuild_index()

        # Discovery: set up tracker backends if configured.
        if self._config.tracker_urls:
            from tessera.discovery.tracker import TrackerBackend

            backends = [TrackerBackend(url) for url in self._config.tracker_urls]
            self._discovery = DiscoveryClient(backends)

        self._started = True

    async def stop(self) -> None:
        """Drain all active swarms and shut down."""
        for entry in self._registry.all_swarms():
            if entry.state in (SwarmState.PENDING, SwarmState.ACTIVE):
                try:
                    self._registry.transition(entry.manifest_hash, SwarmState.DRAINING)
                    self._registry.transition(entry.manifest_hash, SwarmState.CLOSED)
                except Exception:
                    pass
        self._started = False

    async def __aenter__(self) -> TesseraNode:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # publish()
    # ------------------------------------------------------------------

    async def publish(
        self,
        file_path: str | Path,
        metadata: dict[str, str] | None = None,
        skip_moderation: bool = False,
    ) -> bytes:
        """Chunk a file, build the manifest, store it, and begin seeding.

        Args:
            file_path: Path to the source file.
            metadata: Optional key-value pairs. ``name`` defaults to filename.
            skip_moderation: If True, bypass the moderation gate (no-op in
                             Phase 6 — moderation is Phase 7).

        Returns:
            The manifest hash (32 bytes) — the mosaic's permanent identity.
        """
        self._check_started()
        ms = self._ms
        ts = self._ts
        data_dir = self._dd

        if not self._capacity.can_create_swarm(self._registry):
            raise CapacityError(
                self._registry.active_count(),
                self._config.max_swarms_per_node,
            )

        fp = Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(f"file not found: {fp}")

        file_size = fp.stat().st_size
        meta: dict[str, str] = {"name": fp.name}
        if metadata:
            meta.update(metadata)

        # Chunk and collect leaf hashes.
        chunker = Chunker(
            tessera_size=self._config.tessera_size,
            max_payload_size=self._config.max_payload_size,
        )
        builder = ManifestBuilder(
            file_size=file_size,
            tessera_size=self._config.tessera_size,
            metadata=meta,
            max_metadata_keys=self._config.max_metadata_keys,
            max_metadata_value_bytes=self._config.max_metadata_value_bytes,
        )
        chunks: list[tuple[int, bytes]] = []
        for idx, data, leaf_hash in chunker.chunk(fp):
            builder.add_tessera(leaf_hash)
            chunks.append((idx, data))

        manifest_bytes = builder.build()
        manifest_hash = await ms.write(manifest_bytes)

        # Store tesserae.
        for idx, data in chunks:
            await ts.write(manifest_hash, idx, data)

        # Persist seeder state file.
        info = ManifestParser.parse(manifest_bytes)
        state = TransferState.for_seeder(manifest_hash, info.tessera_count)
        await write_state(data_dir, state)

        # Register swarm.
        if not self._registry.has(manifest_hash):
            self._registry.create(manifest_hash, role="seeder")
            self._registry.transition(manifest_hash, SwarmState.ACTIVE)

        # Announce to discovery.
        if self._discovery is not None:
            await self._discovery.announce(manifest_hash, b"\x00" * 32, "seeder")

        # Fire callback.
        if self.on_manifest_created is not None:
            self.on_manifest_created(
                ManifestEvent(
                    manifest_hash=manifest_hash,
                    file_path=str(fp),
                    file_size=file_size,
                    tessera_count=info.tessera_count,
                    metadata=info.metadata,
                )
            )

        return manifest_hash

    # ------------------------------------------------------------------
    # fetch()
    # ------------------------------------------------------------------

    async def fetch(
        self,
        manifest_hash: bytes,
        output_path: str | Path | None = None,
        skip_moderation: bool = False,
        on_progress: Callable[[TransferStatus], None] | None = None,
    ) -> Path:
        """Download a mosaic, assemble, and verify the output file.

        Requires a piece source: either configure tracker_urls in
        TesseraConfig, or inject a test provider via _test_piece_provider.

        Returns:
            Path to the assembled output file.
        """
        self._check_started()
        ms = self._ms
        ts = self._ts
        data_dir = self._dd

        if not self._capacity.can_create_swarm(self._registry):
            raise CapacityError(
                self._registry.active_count(),
                self._config.max_swarms_per_node,
            )

        if not self._registry.has(manifest_hash):
            self._registry.create(manifest_hash, role="leecher")

        # Resolve piece source.
        provider: _PieceSource | None = self._test_piece_provider
        if provider is None:
            # Production path: would use Swarm/MFP (not available without pymfp).
            self._registry.transition(manifest_hash, SwarmState.DRAINING)
            self._registry.transition(manifest_hash, SwarmState.CLOSED)
            raise StarvationError(manifest_hash, 0.0)

        # Acquire and verify manifest.
        raw_manifest = await provider.get_manifest()
        if raw_manifest is None:
            raise TesseraError("peer could not serve manifest")
        info: ManifestInfo = ManifestParser.parse(
            raw_manifest, trusted_hash=manifest_hash
        )
        await ms.write(raw_manifest)

        # on_manifest_received callback.
        out_default = data_dir / info.metadata.get("name", "output")
        out = Path(output_path) if output_path is not None else out_default
        if self.on_manifest_received is not None:
            self.on_manifest_received(
                ManifestEvent(
                    manifest_hash=manifest_hash,
                    file_path=str(out),
                    file_size=info.file_size,
                    tessera_count=info.tessera_count,
                    metadata=info.metadata,
                )
            )

        # Transfer loop.
        verifier = PieceVerifier()
        start_time = time.monotonic()
        bytes_received = 0

        for i in range(info.tessera_count):
            # Resume: skip pieces already on disk.
            if ts.exists(manifest_hash, i):
                continue

            try:
                data = await provider.get_piece(i)
            except TesseraError:
                raise
            except Exception as exc:
                raise TesseraError(
                    f"piece provider failed on piece {i}: {exc}"
                ) from exc
            if data is None:
                raise TesseraError(f"peer could not serve piece {i}")

            if not verifier.verify(data, info.leaf_hashes[i]):
                raise IntegrityError(
                    manifest_hash=manifest_hash,
                    expected=info.leaf_hashes[i],
                    actual=hashlib.sha256(data).digest(),
                )

            await ts.write(manifest_hash, i, data)
            bytes_received += len(data)

            if on_progress is not None:
                on_progress(self._make_transfer_status(manifest_hash, info, i + 1))

        # Assemble and whole-file verify.
        assembler = Assembler(ts)
        await assembler.assemble(manifest_hash, info, out)

        # Persist fetcher state (complete bitfield).
        state = TransferState.for_fetcher(manifest_hash, info.tessera_count)
        complete_bf = Bitfield(info.tessera_count)
        for i in range(info.tessera_count):
            complete_bf.set(i)
        state.set_bitfield(complete_bf)
        state.bytes_downloaded = bytes_received
        await write_state(data_dir, state)

        # Close swarm.
        entry = self._registry.get(manifest_hash)
        if entry.state == SwarmState.PENDING:
            self._registry.transition(manifest_hash, SwarmState.ACTIVE)
        self._registry.transition(manifest_hash, SwarmState.DRAINING)
        self._registry.transition(manifest_hash, SwarmState.CLOSED)

        # on_transfer_complete callback.
        elapsed = time.monotonic() - start_time
        if self.on_transfer_complete is not None:
            self.on_transfer_complete(
                TransferCompleteEvent(
                    manifest_hash=manifest_hash,
                    output_path=str(out),
                    file_size=info.file_size,
                    elapsed=elapsed,
                    peers_used=1,
                    average_throughput=(bytes_received / max(elapsed, 1e-6)),
                )
            )

        return out

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    async def status(
        self,
        manifest_hash: bytes | None = None,
    ) -> TransferStatus | list[TransferStatus] | NodeStatus:
        """Return transfer or node status snapshot."""
        self._check_started()

        if manifest_hash is not None:
            entry = self._registry.get(manifest_hash)
            ms = self._ms
            raw = await ms.read(manifest_hash)
            if raw is None:
                raise KeyError(f"no manifest for {manifest_hash[:8].hex()}")
            info = ManifestParser.parse(raw)
            ts = self._ts
            done = await ts.count(manifest_hash)
            return self._make_transfer_status(manifest_hash, info, done)

        active = [
            e
            for e in self._registry.all_swarms()
            if e.state in (SwarmState.PENDING, SwarmState.ACTIVE)
        ]
        if not active:
            total_peers = sum(len(e.peers) for e in self._registry.all_swarms())
            return NodeStatus(
                agent_id=b"\x00" * 32,
                active_swarms=0,
                total_peers=total_peers,
                capacity_remaining=self._config.max_swarms_per_node,
                ai=AIStatus(
                    active=self._bridge.active,
                    calls_total=self._bridge.calls_total,
                    calls_failed=self._bridge.calls_failed,
                    last_success=self._bridge.last_success,
                    last_failure=self._bridge.last_failure,
                    circuit_breaker_open=self._bridge.circuit_breaker_open,
                ),
            )

        statuses: list[TransferStatus] = []
        for entry in active:
            ms = self._ms
            raw = await ms.read(entry.manifest_hash)
            if raw is None:
                continue
            info = ManifestParser.parse(raw)
            ts = self._ts
            done = await ts.count(entry.manifest_hash)
            statuses.append(self._make_transfer_status(entry.manifest_hash, info, done))
        return statuses

    # ------------------------------------------------------------------
    # cancel()
    # ------------------------------------------------------------------

    async def cancel(self, manifest_hash: bytes) -> None:
        """Cancel an active transfer and leave the swarm."""
        entry = self._registry.get(manifest_hash)
        if entry.state in (SwarmState.PENDING, SwarmState.ACTIVE):
            self._registry.transition(manifest_hash, SwarmState.DRAINING)
            self._registry.transition(manifest_hash, SwarmState.CLOSED)

    # ------------------------------------------------------------------
    # query()
    # ------------------------------------------------------------------

    async def query(
        self,
        text: str,
        max_results: int = 10,
    ) -> list[DiscoveryResult]:
        """Search for mosaics using the Intelligence Bridge (ts-spec-009 §3).

        Returns an empty list when madakit is not configured.
        """
        self._check_started()
        if self._discovery_adapter is None:
            return []
        return await self._discovery_adapter.query(text, max_results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_started(self) -> None:
        if not self._started:
            raise TesseraError(
                "TesseraNode not started — call start() or use async with."
            )

    @property
    def _ms(self) -> ManifestStore:
        assert self._manifest_store is not None
        return self._manifest_store

    @property
    def _ts(self) -> TesseraStore:
        assert self._tessera_store is not None
        return self._tessera_store

    @property
    def _dd(self) -> Path:
        assert self._data_dir is not None
        return self._data_dir

    def _make_transfer_status(
        self,
        manifest_hash: bytes,
        info: ManifestInfo,
        done: int,
    ) -> TransferStatus:
        total = info.tessera_count
        progress = done / total if total > 0 else 1.0
        return TransferStatus(
            manifest_hash=manifest_hash,
            state=SwarmState.ACTIVE,
            mode=TransferMode.NORMAL,
            progress=progress,
            bytes_received=done * info.tessera_size,
            bytes_total=info.file_size,
            throughput_bps=0.0,
            eta_seconds=None,
            tesserae_verified=done,
            tesserae_total=total,
            tesserae_in_flight=0,
            stuck_tesserae=[],
            peers=[],
        )
