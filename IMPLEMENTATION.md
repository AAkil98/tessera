# Implementation Strategy

```yaml
created: 2026-03-20
revised: 2026-03-20
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
status: draft
```

All 13 specifications are complete. This document defines how to turn them into working code — the language ecosystem, package structure, phased build plan, dependency strategy, and development workflow.

---

## 1. Language & Ecosystem

### Python 3.11+

Python is the only viable choice. Both dependencies are Python-native:

| Dependency | Package | Python | Build system |
|-----------|---------|--------|-------------|
| MFP | `pymfp` | ≥ 3.11 | setuptools |
| madakit | `madakit` | ≥ 3.11 | setuptools (src layout) |

Tessera inherits the `≥ 3.11` floor. Key stdlib features used:

| Feature | Min version | Used for |
|---------|------------|----------|
| `asyncio.TaskGroup` | 3.11 | Per-swarm task lifecycle |
| `tomllib` | 3.11 | Config file parsing (no third-party TOML dep) |
| `typing.Protocol` | 3.8+ | Extension points (ChunkingStrategy, DiscoveryBackend, etc.) |
| `dataclasses` | 3.7+ | TesseraConfig, TransferStatus, all public types |
| `hashlib.sha256` | all | Content addressing (delegates to OpenSSL SHA-NI) |
| `struct` | all | Binary wire protocol encoding |
| `asyncio.to_thread` | 3.9+ | Disk I/O offload (ADR-003) |

### Build system

setuptools with `pyproject.toml` — matching both sibling projects. No poetry, no hatch, no flit. One build system across the monorepo.

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"
```

### Dev tooling

| Tool | Purpose | Config |
|------|---------|--------|
| **ruff** | Linting + formatting (replaces flake8, isort, black) | `pyproject.toml [tool.ruff]` |
| **mypy** | Static type checking (`--strict`) | `pyproject.toml [tool.mypy]` |
| **pytest** | Test runner | `pyproject.toml [tool.pytest]` |
| **pytest-asyncio** | Async test support | Auto mode |
| **pytest-cov** | Coverage measurement | Branch coverage on critical paths |
| **pytest-xdist** | Parallel test execution | Unit + integration tests |

### Package manager

The system has `pip` via pyenv. No `uv` or `poetry` installed. Use pip with editable installs for development:

```bash
pip install -e ".[dev]"
pip install -e "../mirror-frame-protocol[dev]"
pip install -e "../mada-modelkit[dev]"
```

---

## 2. Package Structure

### Source layout

Flat layout (matching MFP's `mfp/` convention, not madakit's `src/madakit/`):

```
tessera/
├── pyproject.toml
├── README.md
├── IMPLEMENTATION.md
├── SPECS_BUILD.md
├── SEED_CONTEXT.md
├── specs/                          # Specifications (existing)
│   ├── 01-vision-and-scope.md
│   └── ...
├── tessera/                        # Package root
│   ├── __init__.py                 # Public API exports
│   ├── __main__.py                 # CLI entry point
│   ├── py.typed                    # PEP 561 marker
│   │
│   ├── config.py                   # TesseraConfig, TOML loading, validation
│   ├── errors.py                   # Exception hierarchy
│   ├── types.py                    # Shared types, enums, dataclasses
│   │
│   ├── content/                    # Content addressing (ts-spec-006)
│   │   ├── __init__.py
│   │   ├── chunker.py              # Chunker, ChunkingStrategy, FixedSizeChunking
│   │   ├── manifest.py             # ManifestBuilder, ManifestParser, binary format
│   │   ├── merkle.py               # Merkle tree construction, verification
│   │   └── bitfield.py             # Bitfield operations, serialization
│   │
│   ├── wire/                       # Wire protocol (ts-spec-005)
│   │   ├── __init__.py
│   │   ├── messages.py             # Message types, encode/decode for all 8 types
│   │   ├── state_machine.py        # Peer session state machine
│   │   └── errors.py               # Wire error codes (0x01xx, 0x02xx, 0x03xx)
│   │
│   ├── transfer/                   # Transfer Engine (ts-spec-008)
│   │   ├── __init__.py
│   │   ├── scheduler.py            # Request Scheduler, piece selection
│   │   ├── scorer.py               # Peer Scorer, metrics, thresholds
│   │   ├── pipeline.py             # Request pipeline, concurrency, timeouts
│   │   ├── verifier.py             # Piece Verifier (per-tessera hash check)
│   │   ├── assembler.py            # Assembler (reassembly + whole-file verify)
│   │   └── endgame.py              # Endgame mode logic
│   │
│   ├── swarm/                      # Swarm Manager (ts-spec-007)
│   │   ├── __init__.py
│   │   ├── registry.py             # Swarm Registry, state machine
│   │   ├── connector.py            # Peer Connector, admission sequence
│   │   ├── capacity.py             # Capacity Enforcer, rebalancing
│   │   └── partition.py            # Network partition detection, starvation
│   │
│   ├── discovery/                  # Discovery (ts-spec-007)
│   │   ├── __init__.py
│   │   ├── backend.py              # DiscoveryBackend protocol, PeerRecord
│   │   ├── tracker.py              # TrackerBackend (HTTP client)
│   │   └── client.py               # Discovery Client, multi-source verification
│   │
│   ├── storage/                    # Storage & State (ts-spec-011)
│   │   ├── __init__.py
│   │   ├── layout.py               # Directory layout, path derivation
│   │   ├── manifest_store.py       # Manifest persistence, ManifestIndex
│   │   ├── tessera_store.py        # Tessera persistence, atomic writes
│   │   ├── state.py                # Transfer state files, JSON serialization
│   │   └── gc.py                   # Garbage collection
│   │
│   ├── bridge/                     # Intelligence Bridge (ts-spec-009)
│   │   ├── __init__.py
│   │   ├── bridge.py               # IntelligenceBridge, active/inactive
│   │   ├── discovery_adapter.py    # Discovery Adapter, manifest index search
│   │   ├── selection_adapter.py    # Selection Adapter, AISelectionStrategy
│   │   ├── ranking_adapter.py      # Ranking Adapter, PeerRankingHint
│   │   ├── moderation_adapter.py   # Moderation Adapter, ModerationResult
│   │   └── sanitizer.py            # SanitizationFilter (T9 mitigation)
│   │
│   ├── node.py                     # TesseraNode — main entry point
│   └── cli.py                      # CLI commands (tessera publish/fetch/...)
│
├── tests/
│   ├── conftest.py                 # Shared fixtures (deterministic PRNG, tmp_path)
│   ├── fixtures.py                 # Test fixture generation (tiny/exact/small/medium/empty)
│   ├── unit/
│   │   ├── test_chunker.py
│   │   ├── test_merkle.py
│   │   ├── test_bitfield.py
│   │   ├── test_manifest.py
│   │   ├── test_messages.py
│   │   ├── test_scheduler.py
│   │   ├── test_scorer.py
│   │   ├── test_config.py
│   │   ├── test_errors.py
│   │   └── test_sanitizer.py
│   ├── integration/
│   │   ├── test_publish_flow.py
│   │   ├── test_fetch_assembly.py
│   │   ├── test_transfer_state.py
│   │   ├── test_storage_concurrency.py
│   │   ├── test_manifest_index.py
│   │   └── test_gc.py
│   ├── e2e/
│   │   ├── test_single_transfer.py
│   │   ├── test_multi_seeder.py
│   │   ├── test_swarm_lifecycle.py
│   │   ├── test_cancel_resume.py
│   │   └── test_large_file.py
│   ├── adversarial/
│   │   ├── test_piece_poisoning.py
│   │   ├── test_manifest_tampering.py
│   │   ├── test_protocol_violations.py
│   │   ├── test_sybil.py
│   │   ├── test_withholding.py
│   │   ├── test_discovery_poisoning.py
│   │   ├── test_prompt_injection.py
│   │   └── test_crash_recovery.py
│   ├── ai/
│   │   ├── test_discovery_adapter.py
│   │   ├── test_selection_adapter.py
│   │   ├── test_ranking_adapter.py
│   │   ├── test_moderation_adapter.py
│   │   └── test_degradation.py
│   └── benchmarks/
│       ├── bench_chunking.py
│       ├── bench_hash.py
│       ├── bench_assembly.py
│       ├── bench_single_peer.py
│       ├── bench_multi_peer.py
│       ├── bench_publish_latency.py
│       ├── bench_resume.py
│       └── bench_memory.py
```

### Module-to-spec mapping

| Package | Primary spec | Depends on |
|---------|-------------|-----------|
| `tessera.content` | ts-spec-006 | stdlib only |
| `tessera.wire` | ts-spec-005 | `tessera.content` (bitfield) |
| `tessera.storage` | ts-spec-011 | `tessera.content` (manifest, tessera data) |
| `tessera.transfer` | ts-spec-008 | `tessera.content`, `tessera.wire`, `tessera.storage` |
| `tessera.swarm` | ts-spec-007 | `tessera.wire`, `tessera.transfer` (scorer), pymfp |
| `tessera.discovery` | ts-spec-007 §4–6 | stdlib (httpx for tracker) |
| `tessera.bridge` | ts-spec-009 | madakit (optional), `tessera.content` (manifest metadata) |
| `tessera.node` | ts-spec-010 | all of the above |
| `tessera.cli` | ts-spec-010 §3 | `tessera.node` |

### Dependency direction (strict)

```
cli → node → bridge ──→ madakit (optional)
              ↓
         swarm + transfer
           ↓       ↓
       discovery  storage
           ↓       ↓
          wire ← content
                   ↓
               stdlib only
```

No upward imports. No circular dependencies. `content` and `wire` have zero third-party dependencies.

---

## 3. Dependency Management

### pyproject.toml

```toml
[project]
name = "tessera"
version = "0.1.0"
description = "Secure peer-to-peer file sharing built on MFP and madakit"
requires-python = ">=3.11"
license = {text = "TBD"}
authors = [{name = "Akil Abderrahim"}]
dependencies = [
    "pymfp>=0.1.0",
]

[project.optional-dependencies]
ai = ["madakit>=1.0.0"]
tracker = ["httpx>=0.27"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "pytest-xdist>=3.5",
    "ruff>=0.4",
    "mypy>=1.10",
    "madakit>=1.0.0",
    "httpx>=0.27",
]

[project.scripts]
tessera = "tessera.cli:main"
```

### Dependency rationale

| Dependency | Type | Why |
|-----------|------|-----|
| `pymfp` | Required | Encrypted channels, peer identity, transport — the entire network layer. |
| `madakit` | Optional (`[ai]`) | Intelligence bridge. All AI features degrade silently without it. |
| `httpx` | Optional (`[tracker]`) | HTTP client for TrackerBackend. Could use `urllib` from stdlib but httpx is async-native and already a transitive dep of madakit. |
| stdlib `hashlib` | Built-in | SHA-256. No third-party crypto needed — MFP owns encryption. |
| stdlib `struct` | Built-in | Binary wire protocol encoding. |
| stdlib `tomllib` | Built-in (3.11+) | Config file parsing. |
| stdlib `json` | Built-in | Transfer state files. |
| stdlib `asyncio` | Built-in | Concurrency model (ADR-003). |

### What we do NOT depend on

| Avoided | Why |
|---------|-----|
| protobuf / msgpack | Wire protocol is hand-specified binary for compactness and zero-copy (ts-spec-005). |
| SQLite / any database | Flat files + atomic rename. No external state management (ts-spec-011). |
| click / typer / argparse | CLI is thin enough for `argparse` from stdlib. Revisit if it grows. |
| cryptography | MFP owns all crypto. Tessera uses only `hashlib.sha256`. |
| aiofiles | `asyncio.to_thread()` wrapping standard `open()` is sufficient (ADR-003). |

---

## 4. Phased Implementation Plan

The phases follow the dependency graph bottom-up. Each phase produces testable, self-contained modules. Later phases compose earlier ones.

### Phase 0: Project Scaffolding

**Goal:** Buildable, installable, lintable empty project.

| Task | Deliverable |
|------|------------|
| Create `pyproject.toml` with all metadata, deps, and tool config | Installable package |
| Create package skeleton (`tessera/__init__.py`, `py.typed`, subpackages) | Importable module |
| Configure ruff, mypy, pytest in `pyproject.toml` | `ruff check .` and `mypy tessera/` pass |
| Create `tests/conftest.py` with deterministic fixture generator | Test fixtures available |
| Set up CI pipeline (GitHub Actions: lint → unit → integration) | Green CI on empty project |

**Spec dependencies:** None (infrastructure only).
**Exit criteria:** `pip install -e ".[dev]"` succeeds. `pytest` runs 0 tests and exits 0. `ruff` and `mypy` pass.

---

### Phase 1: Content Addressing

**Goal:** Chunk files, build Merkle trees, serialize/parse manifests.

| Task | Module | Spec |
|------|--------|------|
| Implement `Bitfield` class (set/get/count/serialize/deserialize) | `content/bitfield.py` | ts-spec-005 §4 |
| Implement `FixedSizeChunking` and `ChunkingStrategy` protocol | `content/chunker.py` | ts-spec-006 §2 |
| Implement Merkle tree (build, root hash, odd-node promotion) | `content/merkle.py` | ts-spec-006 §3 |
| Implement `ManifestBuilder` (serialize) and `ManifestParser` (deserialize) | `content/manifest.py` | ts-spec-006 §4–5 |
| Implement shared types (`TesseraConfig`, enums, dataclasses) | `config.py`, `types.py` | ts-spec-010 §4 |
| Implement exception hierarchy | `errors.py` | ts-spec-010 §5 |
| **Unit tests:** Chunker, Merkle, manifest round-trip, bitfield, config, errors | `tests/unit/` | ts-spec-013 §3 |

**Spec dependencies:** ts-spec-006, ts-spec-010 (config + errors only).
**Exit criteria:** Can chunk a file → build manifest → serialize → deserialize → verify root hash. All §3.1–3.9 unit tests pass.

---

### Phase 2: Wire Protocol

**Goal:** Encode, decode, and validate all 8 message types.

| Task | Module | Spec |
|------|--------|------|
| Define message dataclasses (Handshake, Bitfield, Request, Piece, Have, Cancel, Reject, KeepAlive) | `wire/messages.py` | ts-spec-005 §3–4 |
| Implement binary encoder (big-endian, `struct.pack`) | `wire/messages.py` | ts-spec-005 §4 |
| Implement binary decoder with validation | `wire/messages.py` | ts-spec-005 §4 |
| Implement wire error code constants | `wire/errors.py` | ts-spec-005 §7 |
| Implement peer session state machine (HANDSHAKE → BITFIELD → TRANSFER) | `wire/state_machine.py` | ts-spec-005 §3 |
| **Unit tests:** Round-trip all 8 types, truncation, unknown types, big-endian | `tests/unit/` | ts-spec-013 §3.5 |

**Spec dependencies:** ts-spec-005.
**Internal dependencies:** `tessera.content.bitfield` (BITFIELD message payload).
**Exit criteria:** All 8 message types encode/decode correctly. State machine rejects invalid transitions.

---

### Phase 3: Storage Layer

**Goal:** Persist and retrieve manifests, tesserae, and transfer state. Crash-safe.

| Task | Module | Spec |
|------|--------|------|
| Implement directory layout creation and path derivation | `storage/layout.py` | ts-spec-011 §2 |
| Implement manifest store (write-once, read-with-verify, index) | `storage/manifest_store.py` | ts-spec-011 §3 |
| Implement tessera store (atomic write, read, duplicate detection) | `storage/tessera_store.py` | ts-spec-011 §4 |
| Implement transfer state (JSON serialization, write policy, resume) | `storage/state.py` | ts-spec-011 §5 |
| Implement GC (grace period, eligibility, cleanup procedure) | `storage/gc.py` | ts-spec-011 §7 |
| Implement startup cleanup (tmp/, orphan detection, state repair) | `storage/layout.py` | ts-spec-011 §7 |
| **Integration tests:** Publish flow, assembly, state/resume, concurrency, GC | `tests/integration/` | ts-spec-013 §4 |

**Spec dependencies:** ts-spec-011.
**Internal dependencies:** `tessera.content` (manifest format, hashing).
**Exit criteria:** Can write/read manifests and tesserae. Survives simulated crashes (tmp file cleanup, state rebuild from disk). All §4 integration tests pass.

---

### Phase 4: Transfer Engine

**Goal:** Piece selection, peer scoring, request pipeline, verification, assembly.

| Task | Module | Spec |
|------|--------|------|
| Implement rarest-first selection + sequential fallback + random bootstrap | `transfer/scheduler.py` | ts-spec-008 §2 |
| Implement `SelectionStrategy` protocol | `transfer/scheduler.py` | ts-spec-008 §2 |
| Implement peer scorer (4 metrics, EMA, weighted scoring, thresholds) | `transfer/scorer.py` | ts-spec-008 §4 |
| Implement `ScoringFunction` extension point | `transfer/scorer.py` | ts-spec-008 §4 |
| Implement request pipeline (semaphores, timeout, retry, lifecycle) | `transfer/pipeline.py` | ts-spec-008 §5 |
| Implement Piece Verifier (per-tessera SHA-256 check) | `transfer/verifier.py` | ts-spec-006 §7 |
| Implement Assembler (reassembly + whole-file verify) | `transfer/assembler.py` | ts-spec-006 §7, ts-spec-011 §4 |
| Implement endgame mode (entry criteria, duplicate requests, cancellation) | `transfer/endgame.py` | ts-spec-008 §6 |
| **Unit tests:** Piece selection, scoring, endgame activation | `tests/unit/` | ts-spec-013 §3.3–3.4 |

**Spec dependencies:** ts-spec-008, ts-spec-006 §7.
**Internal dependencies:** `tessera.content`, `tessera.wire`, `tessera.storage`.
**Exit criteria:** Given mocked peer bitfields and responses, the scheduler selects correct pieces, scores peers, handles timeouts, activates endgame. Verifier catches bad hashes. Assembler produces correct output.

---

### Phase 5: Swarm Manager

**Goal:** Swarm lifecycle, peer admission/eviction, discovery integration, capacity enforcement.

| Task | Module | Spec |
|------|--------|------|
| Implement Swarm Registry (PENDING → ACTIVE → DRAINING → CLOSED) | `swarm/registry.py` | ts-spec-007 §2 |
| Implement Peer Connector (7-step admission sequence) | `swarm/connector.py` | ts-spec-007 §3 |
| Implement eviction triggers (score, protocol violation, blocklist) | `swarm/connector.py` | ts-spec-007 §3 |
| Implement Capacity Enforcer (per-swarm, per-node limits, rebalancing) | `swarm/capacity.py` | ts-spec-007 §7 |
| Implement `DiscoveryBackend` protocol and `PeerRecord` | `discovery/backend.py` | ts-spec-007 §4 |
| Implement `TrackerBackend` (HTTP client, announce/lookup/unannounce) | `discovery/tracker.py` | ts-spec-007 §5 |
| Implement Discovery Client (multi-source verification, trust scoring) | `discovery/client.py` | ts-spec-007 §6 |
| Implement network partition detection and starvation handling | `swarm/partition.py` | ts-spec-007 §8 |
| Wire up MFP channel establishment (`establish_channel`, `mfp_send`) | `swarm/connector.py` | ts-spec-004 §6 |

**Spec dependencies:** ts-spec-007, ts-spec-004 §6 (MFP boundary).
**Internal dependencies:** `tessera.wire`, `tessera.transfer.scorer`, `tessera.content`.
**Exit criteria:** Can create a swarm, admit peers through the full HANDSHAKE → BITFIELD flow, evict bad peers, enforce capacity limits. TrackerBackend works against a mock HTTP server.

---

### Phase 6: Node & Public API

**Goal:** `TesseraNode` with the 5 public methods. Complete publish and fetch flows.

| Task | Module | Spec |
|------|--------|------|
| Implement `TesseraNode` (init, start, stop, async context manager) | `node.py` | ts-spec-010 §2 |
| Implement `publish()` — Chunker → Manifest → Storage → Announce → Seed | `node.py` | ts-spec-010 §2, ts-spec-004 §4 |
| Implement `fetch()` — Discover → Join → Transfer → Assemble → Verify | `node.py` | ts-spec-010 §2, ts-spec-004 §5 |
| Implement `status()` — TransferStatus, NodeStatus, AIStatus | `node.py` | ts-spec-010 §2 |
| Implement `cancel()` — DRAINING transition, in-flight completion | `node.py` | ts-spec-010 §2 |
| Implement `query()` — delegates to Intelligence Bridge | `node.py` | ts-spec-010 §2 |
| Implement event callbacks (on_manifest_created, on_manifest_received, on_transfer_complete) | `node.py` | ts-spec-010 §6 |
| **E2E tests:** Single transfer, multi-seeder, cancel/resume, large file | `tests/e2e/` | ts-spec-013 §5 |
| **Adversarial tests:** Poisoning, tampering, protocol violations, crash recovery | `tests/adversarial/` | ts-spec-013 §6 |

**Spec dependencies:** ts-spec-010, ts-spec-004.
**Internal dependencies:** All lower packages.
**Exit criteria:** SC1 (two agents exchange 100 MB), SC2 (multi-peer faster than single), SC3 (poisoned piece rejected), SC5 (20-line cycle). All E2E and adversarial tests pass.

---

### Phase 7: Intelligence Bridge

**Goal:** AI-enhanced discovery, selection, ranking, and moderation.

| Task | Module | Spec |
|------|--------|------|
| Implement `IntelligenceBridge` (active/inactive, BaseAgentClient) | `bridge/bridge.py` | ts-spec-009 §2 |
| Implement `SanitizationFilter` (5-rule pipeline) | `bridge/sanitizer.py` | ts-spec-009 §7 |
| Implement Discovery Adapter (manifest index search, LLM prompt, response validation) | `bridge/discovery_adapter.py` | ts-spec-009 §3 |
| Implement Selection Adapter (AISelectionStrategy, one-shot hint, caching) | `bridge/selection_adapter.py` | ts-spec-009 §4 |
| Implement Ranking Adapter (PeerRankingHint, periodic refresh, confidence blending) | `bridge/ranking_adapter.py` | ts-spec-009 §5 |
| Implement Moderation Adapter (publish gate, fetch gate, ModerationResult) | `bridge/moderation_adapter.py` | ts-spec-009 §6 |
| Implement graceful degradation (silent fallback, AIStatus) | `bridge/bridge.py` | ts-spec-009 §8 |
| **AI tests:** All adapters with mock client, degradation, sanitization | `tests/ai/` | ts-spec-013 §8 |

**Spec dependencies:** ts-spec-009.
**Internal dependencies:** `tessera.content` (manifest metadata), `tessera.node` (integration).
**Exit criteria:** SC4 (natural-language discovery with madakit). All AI adapter tests pass with mock client. Silent degradation when madakit absent.

---

### Phase 8: CLI

**Goal:** `tessera` command-line interface wrapping the public API.

| Task | Module | Spec |
|------|--------|------|
| Implement CLI framework (argparse, global options, --json flag) | `cli.py` | ts-spec-010 §3 |
| Implement `tessera publish` | `cli.py` | ts-spec-010 §3 |
| Implement `tessera fetch` (with progress bar) | `cli.py` | ts-spec-010 §3 |
| Implement `tessera query` | `cli.py` | ts-spec-010 §3 |
| Implement `tessera status` | `cli.py` | ts-spec-010 §3 |
| Implement `tessera cancel` | `cli.py` | ts-spec-010 §3 |
| Implement exit codes (0–5) and signal handling (SIGINT/SIGTERM) | `cli.py` | ts-spec-010 §3 |

**Spec dependencies:** ts-spec-010 §3.
**Internal dependencies:** `tessera.node`.
**Exit criteria:** All 5 CLI commands work. `--json` produces valid JSON. Exit codes match spec. Ctrl-C triggers graceful shutdown.

---

### Phase 9: Performance Validation

**Goal:** Benchmark suite, CI integration, budget verification.

| Task | Deliverable | Spec |
|------|------------|------|
| Implement 8 benchmarks (chunking, hash, assembly, single/multi-peer, publish latency, resume, memory) | `tests/benchmarks/` | ts-spec-012 §8, ts-spec-013 §7 |
| Add `@pytest.mark.benchmark` markers and JSON output | pytest config | ts-spec-013 §10 |
| Add benchmark trend tracking to CI (compare against baseline) | CI pipeline | ts-spec-013 §10 |
| Review budgets against measured values, update ts-spec-012 if needed | Spec revision | ts-spec-012 §8 |

**Exit criteria:** All 8 benchmarks run and produce JSON results. Budgets verified against measured values on target hardware.

---

## 5. Phase Summary

```
Phase 0  ─── Scaffolding ──────────────────────────  ~1 day
Phase 1  ─── Content Addressing ───────────────────  ████
Phase 2  ─── Wire Protocol ────────────────────────  ███
Phase 3  ─── Storage Layer ────────────────────────  ████
Phase 4  ─── Transfer Engine ──────────────────────  █████
Phase 5  ─── Swarm Manager ────────────────────────  █████
Phase 6  ─── Node & Public API (SC1–SC5) ──────────  ██████
Phase 7  ─── Intelligence Bridge (SC4) ────────────  ████
Phase 8  ─── CLI ──────────────────────────────────  ██
Phase 9  ─── Performance Validation ───────────────  ███
```

**Critical path:** Phases 0–6 are sequential (each builds on the previous). Phases 7 and 8 can run in parallel after Phase 6.

**First working transfer (SC1):** End of Phase 6.
**Feature-complete (all success criteria):** End of Phase 8.
**Performance-validated:** End of Phase 9.

---

## 6. Implementation Principles

These apply across all phases:

### Code style

- **Type everything.** `mypy --strict` from day one. All function signatures fully annotated. No `Any` unless interfacing with untyped MFP internals.
- **Async by default.** All I/O-touching functions are `async def`. Sync wrappers are not provided — callers use `asyncio.run()`.
- **Protocols over ABCs.** Extension points use `typing.Protocol` for structural subtyping. No inheritance hierarchies for pluggable components.
- **Dataclasses for data.** All public types (TransferStatus, PeerRecord, ModerationResult, etc.) are `@dataclass` — not dicts, not NamedTuples.

### Error handling

- **Fail at boundaries.** Validate inputs in `TesseraNode` methods and the CLI. Internal components trust their callers.
- **Typed exceptions.** Every error path raises a specific `TesseraError` subclass. No bare `Exception` or `ValueError` in public API.
- **Never crash the transfer.** AI failures, single-peer failures, and transient I/O errors are handled internally. Only `IntegrityError`, `StarvationError`, and `CapacityError` propagate to the caller.

### Testing

- **Test the spec, not the implementation.** Test cases are derived from spec requirements, not from internal code structure. If a spec says "odd-node promotion, not duplication," there is a test that verifies promotion and a test that proves duplication produces a different (wrong) result.
- **Real I/O in integration tests.** No mocking of filesystem or MFP channels beyond unit tests. Integration and E2E tests use `tmp_path` and MFP loopback.
- **Adversarial from Phase 6.** Once the node works end-to-end, adversarial tests are written alongside feature tests — not deferred.

### MFP boundary

- Import only from `mfp`'s public API: `bind`, `establish_channel`, `mfp_send`, `mfp_channels`, `RuntimeConfig`.
- Never access MFP internals (ratchet state, key material, frame encoding).
- SHA-256 for content addressing uses `hashlib`, not MFP's crypto primitives.

### madakit boundary

- All access through `IntelligenceBridge`.
- No lower layer (transfer, swarm, storage) ever imports from `madakit`.
- The bridge accepts any `BaseAgentClient` — never imports a specific provider.
- Every bridge method has a `if not self.active: return fallback` guard as the first line.

---

## 7. Development Workflow

### Branch strategy

- `main` — stable. Protected. PRs only.
- `dev` — integration branch. Phases merge here first.
- `phase/N-name` — per-phase feature branches (e.g., `phase/1-content-addressing`).

### Commit convention

```
<type>(<scope>): <description>

Types: feat, fix, test, refactor, docs, chore
Scopes: content, wire, storage, transfer, swarm, discovery, bridge, node, cli, ci
```

### PR checklist (per phase)

- [ ] All new code has type annotations (`mypy --strict` passes)
- [ ] `ruff check` passes
- [ ] Unit tests cover the spec's test cases for this module
- [ ] Integration tests (if phase ≥ 3) pass
- [ ] No new dependencies without justification
- [ ] Spec cross-references are correct (module docstrings cite spec sections)

### CI pipeline

See ts-spec-013 §10 for the full pipeline. Summary:

| Stage | Trigger | Blocks merge |
|-------|---------|:---:|
| Lint (ruff + mypy) | Every commit | Yes |
| Unit tests | Every commit | Yes |
| Integration + E2E + Adversarial | Every PR | Yes |
| Benchmarks | Every PR | No (advisory) |

---

## 8. Open Decisions

| Decision | Options | Recommendation | When to decide |
|----------|---------|----------------|----------------|
| **HTTP client for TrackerBackend** | `httpx` (async-native) vs `urllib.request` (stdlib, sync) | `httpx` — async-native, already a madakit transitive dep. Make it an optional dep (`[tracker]`). | Phase 5 |
| **CLI framework** | `argparse` (stdlib) vs `click` | `argparse` — no new dep, CLI is thin. Switch to click only if subcommand complexity grows. | Phase 8 |
| **License** | Apache-2.0 (matching MFP) vs MIT (matching madakit) | Apache-2.0 — matches the primary dependency and provides patent grant. | Before first public release |
| **Tracker server implementation** | In-repo vs separate project | Separate project — the tracker is infrastructure, not the library. Ship a reference implementation in `tools/` or a sibling repo. | Phase 5 |
| **CI provider** | GitHub Actions vs other | GitHub Actions — repo is already on GitHub. | Phase 0 |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
