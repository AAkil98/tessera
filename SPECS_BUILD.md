# SPECS_BUILD — Specification Build Journal

This file tracks the drafting of Tessera's specification documents, logs architectural decisions, and records open questions as they arise.

---

## Document Tracker

| # | Document | Status | Started | Completed | Notes |
|---|----------|--------|---------|-----------|-------|
| 1 | Vision & Scope | Complete | 2026-03-13 | 2026-03-13 | `specs/01-vision-and-scope.md` |
| 2 | Glossary | Complete | 2026-03-13 | 2026-03-13 | `specs/02-glossary.md` |
| 3 | Threat Model | Complete | 2026-03-13 | 2026-03-13 | `specs/03-threat-model.md` |
| 4 | System Architecture | Complete | 2026-03-13 | 2026-03-13 | `specs/04-system-architecture.md` |
| 5 | Wire Protocol Addendum | Complete | 2026-03-14 | 2026-03-14 | `specs/05-wire-protocol-addendum.md` |
| 6 | Content Addressing Spec | Complete | 2026-03-14 | 2026-03-14 | `specs/06-content-addressing.md` |
| 7 | Swarm & Peer Discovery | Complete | 2026-03-16 | 2026-03-16 | `specs/07-swarm-and-peer-discovery.md` |
| 8 | Piece Selection & Transfer Strategy | Complete | 2026-03-16 | 2026-03-16 | `specs/08-piece-selection-and-transfer.md` |
| 9 | AI Integration Spec | Complete | 2026-03-17 | 2026-03-17 | `specs/09-ai-integration.md` |
| 10 | API & CLI Design | Complete | 2026-03-17 | 2026-03-17 | `specs/10-api-and-cli.md` |
| 11 | Storage & State Management | Complete | 2026-03-17 | 2026-03-17 | `specs/11-storage-and-state.md` |
| 12 | Performance Budget | Complete | 2026-03-18 | 2026-03-18 | `specs/12-performance-budget.md` |
| 13 | Test & Validation Plan | Complete | 2026-03-19 | 2026-03-20 | `specs/13-test-and-validation.md` |

---

## Architectural Decision Log

### ADR-001: Repository and Dependency Structure
- **Date:** 2026-03-13
- **Context:** Tessera depends on two sibling libraries — MFP (secure P2P comms) and madakit (AI/LLM interface). Need to decide how they relate at the package level.
- **Decision:** Tessera is a standalone project that imports MFP and madakit as dependencies. It is not a plugin or extension of either. New code (chunking, swarm logic, tracker) lives entirely in this repo.
- **Status:** Accepted

### ADR-002: Specification-First Development
- **Date:** 2026-03-13
- **Context:** The intersection of encrypted P2P protocols, torrent mechanics, and AI integration has enough moving parts that jumping straight to code would create rework.
- **Decision:** Draft all 13 specification documents before writing implementation code. Documents are ordered by dependency — later specs build on decisions made in earlier ones.
- **Status:** Accepted

---

## Open Questions

- [x] **Naming:** Tessera. Resolved 2026-03-13.
- [x] **Chunk size:** Fixed-size default (256KB), adaptive via `ChunkingStrategy` extension point. MFP's 1MB max_payload is the ceiling per tessera. Resolved 2026-03-13.
- [x] **Tracker model:** Modal by default, hybrid-capable. Config declares which `DiscoveryBackend` implementations are active; if multiple, the Discovery Client cross-references results (T8 mitigation). Resolved 2026-03-13.
- [x] **Scope of AI integration:** Optional enhancement. Core transfer protocol works without it. Resolved in spec 01, section 6.
- [x] **Target scale:** Tens to hundreds of peers (private/semi-private networks). Resolved in spec 01, NG3.
- [x] **Manifest mutability:** Immutable. A manifest's hash is the mosaic's identity; new content produces a new hash, therefore a new mosaic. Version tracking (mapping a human-readable name to a sequence of manifest hashes) is a higher-level concern, not part of the wire protocol or content addressing layer. Resolved 2026-03-13.
- [x] **Multi-file mosaics:** Mosaic = one file. Directory sharing is deferred as a future "collection" type (a manifest whose payload is a list of other manifest hashes + relative paths). Keeps the Transfer Engine simple. Resolved 2026-03-13.
- [x] **Configuration surface:** Owned by spec 10 (API & CLI Design) as a `TesseraConfig` dataclass with defaults. Other specs reference configurable values but do not define the config object. Resolved 2026-03-13.
- [x] **Error handling strategy:** Distributed by domain — network partition in spec 07 (Swarm & Peer Discovery), MFP crash recovery and partial disk write failures in spec 11 (Storage & State Management). Resolved 2026-03-13.
- [ ] **License:** Deferred until project is mature.

### ADR-003: Concurrency Model — asyncio + Thread Pool
- **Date:** 2026-03-13
- **Context:** Tessera needs async I/O for MFP channels, disk reads/writes, and discovery queries. Evaluated asyncio, trio, threading, and multiprocessing.
- **Decision:** asyncio for all I/O concurrency (MFP is asyncio-native). `asyncio.to_thread()` for blocking operations (disk I/O, CPU-heavy hashing). trio rejected due to asyncio-trio bridge overhead when MFP is already asyncio-native. multiprocessing reserved for future CPU-bound optimization if profiling warrants it.
- **Status:** Accepted

### ADR-004: Fixed-Size Tesserae with Extensible Chunking
- **Date:** 2026-03-13
- **Context:** Adaptive (content-defined) chunking enables cross-version deduplication but complicates bitfield semantics, Merkle tree construction, and the Assembler. The target scale (tens-to-hundreds of peers) does not require dedup optimization.
- **Decision:** Default to fixed-size tesserae (256KB). The Chunker accepts a `ChunkingStrategy` protocol, allowing adaptive chunking to be added as an extension without modifying the Transfer Engine.
- **Status:** Accepted

### ADR-005: Immutable Manifests
- **Date:** 2026-03-13
- **Context:** Spec 03 (T3 mitigation) implied manifests could be versioned, but the content addressing model (manifest hash = mosaic identity) implies immutability. Versioned manifests would require a mutable identity layer, complicating the protocol.
- **Decision:** Manifests are immutable. Changing content produces a new manifest hash, therefore a new mosaic. Logical versioning (tracking successive versions of a file) is a higher-level concern outside the core protocol.
- **Status:** Accepted

### ADR-006: Single-File Mosaics
- **Date:** 2026-03-13
- **Context:** Spec 01 refers to "a file" but never clarifies whether a mosaic can represent a directory. Supporting multi-file mosaics adds complexity to the manifest format, Chunker, and Assembler.
- **Decision:** A mosaic is always a single file. Directory sharing can be supported later via a "collection" type — a manifest whose payload references other manifest hashes with relative paths. This keeps the Transfer Engine simple for v1.
- **Status:** Accepted

---

## Session Log

### 2026-03-13 — Project Inception
- Conducted feasibility analysis of building a torrent-like app on MFP + madakit
- MFP provides: encrypted bilateral channels, agent lifecycle, temporal ratchet, federation transport, wire protocol
- madakit provides: LLM abstraction, composable middleware (retry, circuit breaker, load balancing, caching), workflow engine
- Identified 13 specification documents needed before implementation
- Created repository, README, and this journal
- Next: Begin drafting Document 1 (Vision & Scope)

### 2026-03-13 — Document 1 Complete
- Drafted and approved all 8 sections of Vision & Scope (ms-spec-001)
- Key decisions captured: madakit is optional (G5, section 6), target scale is tens-to-hundreds (NG3), no BitTorrent compatibility (NG1)
- 7 goals, 5 non-goals, 6 success criteria defined
- Next: Document 2 (Glossary)

### 2026-03-13 — Document 2 Complete
- Drafted and approved all 4 sections of Glossary (ts-spec-002)
- Established 11 Tessera-native terms (tessera, mosaic, manifest, hash tree, swarm, seeder, leecher, publisher, publish, fetch, manifest hash)
- Mapped 10 MFP terms and 4 madakit terms to their roles in Tessera
- Redefined 8 BitTorrent terms with Tessera-specific semantics
- Next: Document 3 (Threat Model)

### 2026-03-13 — Document 3 Complete
- Drafted and approved all 7 sections of Threat Model (ts-spec-003)
- 5 trust assumptions, 7 assets, 5 threat actors, 10 threats cataloged
- 5 mitigations inherited from MFP, 8 requiring new implementation
- 6 out-of-scope threats documented with rationale
- Cross-references established to specs 006, 007, 008, 009
- Next: Document 4 (System Architecture)

### 2026-03-13 — Document 4 Complete
- Drafted and approved all 8 sections of System Architecture (ts-spec-004)
- 4-layer architecture: MFP Runtime → Transfer Engine / Swarm Manager → Application Interface → Intelligence Layer
- 13 subcomponents defined across 3 Tessera-owned layers
- Publish (11 steps) and Fetch (23 steps) data flows documented
- Strict dependency boundaries: MFP public API only, madakit behind Intelligence Bridge
- Async-first concurrency model with per-swarm task isolation
- 5 extension points via typing.Protocol for pluggable backends
- Next: Document 5 (Wire Protocol Addendum)

### 2026-03-13 — Open Questions & Gaps Resolution
- Resolved 7 open questions from SEED_CONTEXT review of specs 01–04
- Chunk size: fixed 256KB default, adaptive via extension point (ADR-004)
- Tracker model: modal by default, hybrid-capable via DiscoveryBackend protocol
- Manifest mutability: immutable; each version is a new mosaic (ADR-005)
- Multi-file mosaics: mosaic = one file; collections deferred (ADR-006)
- Configuration surface: owned by spec 10 as TesseraConfig dataclass
- Error handling: distributed by domain across specs 07 and 11
- Concurrency: asyncio + thread pool confirmed, trio/multiprocessing rejected for now (ADR-003)
- License: deferred until project is mature
- Recorded ADRs 003–006
- Glossary gaps (spec 02) and cross-spec consistency items remain open — mechanical fixes to apply before spec phase closes
- Next: Scaffold and draft Document 5 (Wire Protocol Addendum)

### 2026-03-14 — Document 5 Complete
- Drafted and approved all 9 sections of Wire Protocol Addendum (ts-spec-005)
- 8 message types: HANDSHAKE, BITFIELD, REQUEST, PIECE, HAVE, CANCEL, REJECT, KEEP_ALIVE
- Binary encoding, big-endian, 1-byte type tag, no serialization framework
- State machine: HANDSHAKE → BITFIELD → transfer phase
- Payload constraints: tessera_size + 5 ≤ max_payload_size; 256KB default fits within MFP's 1MB default
- 12 error codes across 3 ranges: protocol (0x01xx), transfer (0x02xx), capacity (0x03xx)
- Extensibility: 0x80–0xFF reserved for extension messages, silently ignored if unrecognized
- Single protocol version; no multi-version negotiation
- Next: Document 6 (Content Addressing Spec)

### 2026-03-14 — Document 6 Complete
- Drafted and approved all 8 sections of Content Addressing Spec (ts-spec-006)
- Fixed-size chunking (256KB default) with ChunkingStrategy extension point
- Merkle tree with odd-node promotion (not duplication)
- Binary manifest format: 4-byte magic ("TSRA"), fixed 60-byte header, sorted key-value metadata, flat leaf hash array
- Manifest hash = SHA-256 of entire serialized manifest; immutability enforced (ADR-005)
- Three manifest transfer strategies: inline (≤1MB), chunked (>1MB via reserved PIECE indices), out-of-band
- Three-level integrity verification: manifest hash check, per-tessera hash check, whole-file re-verification
- Reserved PIECE index 0xFFFFFFFF for manifest delivery; downward counting for chunked manifests
- Next: Document 7 (Swarm & Peer Discovery)

### 2026-03-16 — Document 7 Complete
- Drafted and approved all 9 sections of Swarm & Peer Discovery (ts-spec-007)
- 4 swarm states: PENDING → ACTIVE → DRAINING → CLOSED
- 7-step peer admission sequence with failure handling for each step
- Eviction triggers: score threshold, protocol violation, hash mismatches, MFP quarantine, capacity rebalancing
- Per-swarm blocklist for evicted malicious peers
- DiscoveryBackend protocol: announce(), lookup(), unannounce() with full contract
- Default TrackerBackend: centralized HTTPS tracker with announce refresh and TTL expiry
- Multi-source verification: concurrent lookup across backends, trust scoring (high/medium/low), connection ordering
- Capacity enforcement: max_peers_per_swarm (50), max_swarms_per_node (10), rebalancing with eviction_threshold
- Network partition handling: 3 detection mechanisms, reconnection via re-discovery (not per-peer), swarm starvation with exponential backoff, transfer resumption from disk state
- Next: Document 8 (Piece Selection & Transfer Strategy)

### 2026-03-16 — Document 8 Complete
- Drafted and approved all 8 sections of Piece Selection & Transfer Strategy (ts-spec-008)
- Piece selection: rarest-first default, sequential fallback (single peer or near-completion), random-first bootstrap (4 initial requests), SelectionStrategy extension point
- Peer selection: score-based ranking with load-balancing via effective_score, AI-driven ranking hints, backlog for unschedulable tesserae
- Peer scoring: 4 metrics (latency EMA, failure rate, bytes delivered, hash mismatches), weighted linear scoring function, ScoringFunction extension point, 3 thresholds (min 0.1, eviction 0.2, deprioritization 0.3)
- Request pipeline: per-peer (5) and per-swarm (20) concurrency via semaphores, 7-state request lifecycle, timeout handling with cooldown, retry policy with max 10 retries, stuck tessera reporting
- Endgame mode: entry at ≤20 remaining + all requested, duplicate requests to all holders, CANCEL on first completion, max 100 endgame requests
- Transfer metrics: TransferStatus dataclass with progress, throughput (10s sliding window), ETA, per-peer and swarm-level metrics
- Next: Document 9 (AI Integration Spec)

### 2026-03-17 — Document 9 Complete
- Drafted and approved all 9 sections of AI Integration Spec (ts-spec-009)
- Intelligence Bridge architecture: 5 adapters (Discovery, Selection, Ranking, Moderation, Sanitization) behind single BaseAgentClient interface
- Content discovery: natural-language query → manifest hash via LLM, manifest index, DiscoveryResult with relevance scoring
- Smart piece selection: one LLM call per mosaic, cached priority overlay on rarest-first, AISelectionStrategy wrapping fallback
- Smart peer ranking: periodic LLM calls (60s interval), PeerRankingHint with confidence-based blending, guardrails prevent LLM from overriding safety constraints
- Content moderation: publish gate and fetch gate via ModerationResult, caller-controlled policy prompts
- Metadata sanitization: 5-rule pipeline (truncation, control chars, newline normalization, injection pattern stripping, Unicode normalization), mandatory before all LLM calls, T9 mitigation
- Graceful degradation: silent fallback for every adapter, AIStatus observability dataclass, transfer never fails due to LLM unavailability
- Next: Document 10 (API & CLI Design)

### 2026-03-17 — Document 10 Complete
- Drafted and approved all 7 sections of API & CLI Design (ts-spec-010)
- TesseraNode class: async context manager with start/stop, 5 public methods (publish, fetch, query, status, cancel)
- SC5 demonstration: 14-line publish-discover-fetch cycle
- CLI: 5 commands mapping 1:1 to API methods, global options (--config, --data-dir, --bind, --tracker, --log-level, --json), 6 exit codes
- TesseraConfig: 30-field dataclass centralizing all configurable values from specs 06–09, TOML file format, 4-tier precedence
- Exception hierarchy: TesseraError base with 7 subclasses (ModerationError, CapacityError, StarvationError, IntegrityError, ProtocolError, HandshakeError, MessageError, ConfigError), recoverability table
- Event callbacks: on_manifest_created, on_manifest_received, on_transfer_complete, synchronous non-blocking with exception isolation
- Next: Document 11 (Storage & State Management)

### 2026-03-17 — Document 11 Complete
- Drafted and approved all 8 sections of Storage & State Management (ts-spec-011)
- Directory layout: 5 top-level entries (manifests/, tesserae/, transfers/, tmp/, node.id), 2-char hex prefix for manifests, per-mosaic tessera directories, 0o700/0o600 permissions
- Manifest store: write-once with atomic rename, read-with-verify, ManifestIndex for AI discovery, linear rebuild on startup
- Tessera store: per-mosaic directories, 6-digit zero-padded indices, hash verification on write (not read), sequential assembly with whole-file verification
- Transfer state: JSON format with bitfield/retry counts/peers, write on 5% progress / state transitions / shutdown, disk-derived bitfield authoritative on resume
- Concurrency: no file locking needed (content-addressable + atomic rename + single-writer), asyncio.to_thread() for all disk I/O
- Crash recovery: 5 scenarios (tessera write, state write, assembly, disk full, corrupt piece) all self-healing via temp cleanup + disk scan + re-verification
- Garbage collection: post-transfer automatic with 60s grace period, manifest retention by default, startup cleanup of tmp/ and orphaned directories
- Next: Document 12 (Performance Budget)

### 2026-03-20 — Implementation Strategy Prepared
- Created IMPLEMENTATION.md with complete build plan
- Language & ecosystem: Python 3.11+, setuptools, ruff + mypy + pytest
- Package structure: 9 subpackages mapping to spec layers, strict dependency direction
- 10 phases (0–9): scaffolding → content → wire → storage → transfer → swarm → node → bridge → CLI → benchmarks
- Critical path: Phases 0–6 sequential, 7–8 parallelizable after 6
- First working transfer (SC1) at end of Phase 6, feature-complete at Phase 8
- Dependencies: pymfp (required), madakit (optional), httpx (optional for tracker), zero other third-party deps
- 5 open decisions documented (HTTP client, CLI framework, license, tracker server, CI provider)
- Updated README.md, SPECS_BUILD.md with spec 13 completion

### 2026-03-20 — Document 13 Complete
- Drafted and approved all 11 sections of Test & Validation Plan (ts-spec-013)
- Sections 1–2: purpose, testing philosophy (real I/O, deterministic hashing, adversarial by default), 4 test layers, 5 fixture files, tooling
- Section 3: 9 unit test subsections with ~80 individual test cases covering chunker, Merkle tree, piece selector, peer scorer, protocol serializer (all 8 types), manifest builder/parser, bitfield, config, exceptions
- Section 4: 6 integration test subsections (publish flow, fetch assembly, transfer state/resume, storage concurrency, manifest index, GC)
- Section 5: 5 E2E test groups (single/multi-seeder, swarm lifecycle, cancel/resume, large file)
- Section 6: 10 adversarial test groups mapping to T1–T10 threats plus protocol violations, crash recovery
- Section 7: 8 benchmarks tied to ts-spec-012 budgets, violation policy, local benchmarking workflow
- Section 8: AI adapter tests with mock BaseAgentClient, graceful degradation, sanitization filter
- Section 9: Platform matrix (Python 3.11–3.13, Linux/macOS/Windows)
- Section 10: 4-stage CI pipeline, gating rules, 90% branch coverage on critical components, benchmark trend tracking, pytest markers, flaky test policy
- Section 11: References to all 12 prior specs

### 2026-03-18 — Document 12 Complete
- Drafted and approved all 9 sections of Performance Budget (ts-spec-012)
- Transfer throughput: ≤15% overhead over raw MFP, multi-peer scaling (5 peers → 3.5×, 10 → 6×, 20+ → 8×), absolute floors (50 MB/s single-peer LAN)
- Latency: publish ≤1.5s/GB + 500ms, time-to-first-byte ≤1.5s LAN, assembly ≤3s/GB, status() ≤1ms, startup ≤5s with 10 transfers
- Memory: per-swarm ≤10MB (dominated by in-flight pieces), per-node ≤150MB at capacity, file data never cached in memory
- Disk I/O: 1.0× write amplification, no fsync (except node.id), sequential assembly, thread pool as natural backpressure throttle
- CPU: dominated by SHA-256 hashing (~0.1ms per 256KB tessera), all other computation negligible, thread pool sizing sufficient
- Scalability: file size scaling to 100GB (400K tesserae), peer scaling to 500 (manageable but beyond target), predictable degradation at all limits
- Measurement: 8 development benchmarks, debug-level performance logging, budget review cadence
- Next: Document 13 (Test & Validation Plan)
