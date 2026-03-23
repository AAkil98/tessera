# System Architecture

```yaml
id: ts-spec-004
type: spec
status: draft
created: 2026-03-13
revised: 2026-03-14
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [architecture, system-design, tessera]
```

## Table of Contents

1. Architecture Overview
2. Layer Diagram
3. Component Descriptions
4. Data Flow: Publish
5. Data Flow: Fetch
6. Dependency Boundaries
7. Concurrency Model
8. Extension Points
9. References

---

## 1. Architecture Overview

Tessera is organized as four layers stacked on top of two external dependencies. Each layer has a single responsibility and communicates only with its immediate neighbors.

From bottom to top:

- **MFP Runtime** (external) — Provides peer identity, encrypted channels, message pipeline, and federation transport. Tessera never touches raw sockets or cryptographic primitives directly.
- **Transfer Engine** — Manages tessera exchange: piece requests, bitfield negotiation, hash verification, peer scoring, and reassembly. This is the core of Tessera.
- **Swarm Manager** — Manages swarm lifecycle: joining, leaving, peer tracking, capacity enforcement, and discovery service interaction.
- **Application Interface** — The public API and CLI that humans and agents use to publish, fetch, and query mosaics.
- **Intelligence Layer** (optional, external) — madakit middleware for content discovery, smart selection, and moderation. Accessed through the Application Interface; never coupled to lower layers.

Each layer is a Python module with an explicit public interface. No layer imports from a layer above it. The Transfer Engine and Swarm Manager together form Tessera's core — they contain all protocol logic that is neither inherited from MFP nor optional via madakit.

## 2. Layer Diagram

```
┌─────────────────────────────────────────────────┐
│              Intelligence Layer                  │
│          (madakit — optional dependency)          │
│  content discovery · smart selection · moderation │
└────────────────────┬────────────────────────────┘
                     │ BaseAgentClient interface
┌────────────────────▼────────────────────────────┐
│            Application Interface                 │
│         public API · CLI · agent tools           │
│     publish() · fetch() · query() · status()     │
└──────┬─────────────────────────────────┬────────┘
       │                                 │
┌──────▼──────────┐          ┌───────────▼────────┐
│  Swarm Manager  │◄────────►│  Transfer Engine   │
│                 │          │                     │
│ join/leave      │          │ piece requests      │
│ peer tracking   │          │ bitfield exchange   │
│ capacity limits │          │ hash verification   │
│ discovery       │          │ peer scoring        │
│                 │          │ reassembly          │
└──────┬──────────┘          └───────────┬────────┘
       │                                 │
┌──────▼─────────────────────────────────▼────────┐
│               MFP Runtime                        │
│          (external dependency)                   │
│  AgentId · channels · ratchet · federation · TCP │
└─────────────────────────────────────────────────┘
```

The Swarm Manager and Transfer Engine sit at the same level and communicate laterally. The Swarm Manager tells the Transfer Engine which peers are available; the Transfer Engine tells the Swarm Manager when a peer should be scored down or disconnected. Neither depends on the Application Interface above or accesses MFP internals below — they use MFP's public API (`bind`, `mfp_send`, `mfp_channels`).

## 3. Component Descriptions

### 3.1 Transfer Engine

The Transfer Engine is responsible for moving tesserae between peers and guaranteeing that every piece matches the manifest.

| Subcomponent | Responsibility |
|-------------|----------------|
| **Chunker** | Splits a file into tesserae of configured size (default 256KB, max 1MB per MFP `max_payload`). Accepts a `ChunkingStrategy` protocol for alternative algorithms (e.g., content-defined chunking). Builds the Merkle hash tree. Produces the manifest. Used during publish. |
| **Assembler** | Writes verified tesserae to their position on disk. Detects completion. Performs final whole-file hash check. Used during fetch. |
| **Piece Verifier** | Hashes each received tessera and validates it against the corresponding leaf in the hash tree. Rejects mismatches immediately (mitigates T1). |
| **Request Scheduler** | Decides which tesserae to request from which peers. Implements rarest-first selection, endgame mode, and concurrent request limits. Accepts hints from the Intelligence Layer when available. |
| **Peer Scorer** | Tracks per-peer metrics: serve latency, failure rate, bytes delivered. Feeds scores to the Request Scheduler for prioritization and to the Swarm Manager for disconnect decisions. |
| **Bitfield Manager** | Maintains the local bitfield (which tesserae this peer holds). Exchanges bitfields with peers on channel establishment. Processes HAVE announcements. |

### 3.2 Swarm Manager

The Swarm Manager is responsible for the set of peers participating in a mosaic's transfer.

| Subcomponent | Responsibility |
|-------------|----------------|
| **Swarm Registry** | Maps manifest hashes to active swarms. Tracks membership, capacity, and state for each swarm. A peer may be registered in multiple swarms. |
| **Peer Connector** | Establishes and tears down MFP channels with peers. Handles the join handshake (manifest hash exchange, bitfield swap). |
| **Discovery Client** | Queries the discovery service to find peers for a given manifest hash. Supports multiple discovery backends (centralized, gossip, manual). Cross-references results when multiple sources are available (mitigates T8). |
| **Capacity Enforcer** | Enforces maximum peer count per swarm and maximum swarm count per node. Rejects new joins when limits are reached (mitigates T4). |

### 3.3 Application Interface

The Application Interface is the boundary between Tessera internals and the outside world.

| Subcomponent | Responsibility |
|-------------|----------------|
| **Public API** | Python functions: `publish()`, `fetch()`, `query()`, `status()`, `cancel()`. The library entry point. Designed for both human callers and agent callers (G6). |
| **CLI** | Command-line wrapper around the Public API. Provides `tessera publish`, `tessera fetch`, `tessera status`, etc. |
| **Intelligence Bridge** | Optional adapter that connects madakit's `BaseAgentClient` to the Request Scheduler and Discovery Client. When madakit is not installed, this component is a no-op. |

## 4. Data Flow: Publish

```
User/Agent
    │
    ▼  publish(file_path)
Application Interface
    │
    ▼
Transfer Engine: Chunker
    │  1. Read file from disk
    │  2. Split into tesserae of configured size
    │  3. Hash each tessera (SHA-256)
    │  4. Build Merkle hash tree
    │  5. Produce manifest (metadata + hash tree root + tessera hashes)
    │  6. Compute manifest hash (SHA-256 of manifest)
    │  7. Write tesserae to local storage
    │
    ▼
Swarm Manager
    │  8. Create a new swarm entry in Swarm Registry (manifest hash → this peer)
    │  9. Register with discovery service (announce manifest hash + AgentId)
    │  10. Bind as MFP agent if not already bound
    │
    ▼
Application Interface
    │  11. Return manifest hash to caller
    ▼
User/Agent
```

The publisher is now a seeder. Incoming channel requests from fetchers are handled by the Swarm Manager (peer admission) and Transfer Engine (serving tesserae).

## 5. Data Flow: Fetch

```
User/Agent
    │
    ▼  fetch(manifest_hash)
Application Interface
    │
    ▼
Swarm Manager: Discovery Client
    │  1. Query discovery service for peers holding this manifest hash
    │  2. Cross-reference results if multiple sources available (T8 mitigation)
    │
    ▼
Swarm Manager: Peer Connector
    │  3. Establish MFP bilateral channels with discovered peers
    │  4. Join handshake: exchange manifest hash, receive manifest from first peer
    │  5. Verify manifest hash matches requested hash (T2 mitigation)
    │  6. Register in Swarm Registry as leecher
    │
    ▼
Transfer Engine: Bitfield Manager
    │  7. Receive bitfields from all connected peers
    │  8. Initialize local bitfield (all zeros)
    │
    ▼
Transfer Engine: Request Scheduler
    │  ┌─── loop until all tesserae received ───┐
    │  │  9. Select next tessera(e) to request    │
    │  │     (rarest-first, or AI-hinted)         │
    │  │  10. Select peer(s) to request from      │
    │  │     (best score, or AI-ranked)            │
    │  │  11. Send request via MFP channel         │
    │  │                                           │
    │  │  Transfer Engine: Piece Verifier          │
    │  │  12. Receive tessera payload              │
    │  │  13. SHA-256 hash and verify against      │
    │  │      Merkle tree leaf (T1 mitigation)     │
    │  │  14. On mismatch: reject, score peer      │
    │  │      down, re-request from another peer   │
    │  │  15. On match: pass to Assembler          │
    │  │                                           │
    │  │  Transfer Engine: Assembler               │
    │  │  16. Write tessera to disk position       │
    │  │  17. Update local bitfield                │
    │  │  18. Broadcast HAVE to connected peers    │
    │  └───────────────────────────────────────────┘
    │
    ▼
Transfer Engine: Assembler
    │  19. All tesserae received — final whole-file hash check
    │  20. Mark mosaic complete
    │
    ▼
Swarm Manager
    │  21. Transition from leecher to seeder
    │  22. Continue serving tesserae to other peers
    │
    ▼
Application Interface
    │  23. Return assembled file path to caller
    ▼
User/Agent
```

At any point during the loop, the Peer Scorer feeds metrics to the Request Scheduler (peer prioritization) and Swarm Manager (disconnect decisions). If madakit is active, the Intelligence Bridge may inject hints at steps 9 and 10.

## 6. Dependency Boundaries

Tessera enforces strict boundaries with its two external dependencies. These rules ensure that swapping, upgrading, or removing a dependency does not ripple through the codebase.

### MFP Boundary

| Rule | Rationale |
|------|-----------|
| Tessera imports only from `mfp`'s public API: `Runtime`, `RuntimeConfig`, `bind`, `unbind`, `mfp_send`, `mfp_channels`, `mfp_status`, `AgentHandle`, `AgentId`, `ChannelId`, `ChannelInfo`, `Receipt`. | No coupling to MFP internals (pipeline stages, storage engine, ratchet state). |
| Tessera never constructs `Frame`, `Block`, `StateValue`, or `ProtocolMessage` objects directly. | Frame construction is MFP's responsibility. Tessera treats the channel as an opaque encrypted pipe. |
| Tessera never calls MFP's cryptographic primitives (`hmac_sha256`, `chacha20`) for its own purposes. It uses Python's `hashlib.sha256` for tessera hashing. | Keeps Tessera's crypto needs (content hashing) separate from MFP's crypto needs (channel encryption). Avoids tight coupling to MFP's `cryptography` library version. |

### madakit Boundary

| Rule | Rationale |
|------|-----------|
| All madakit access goes through the Intelligence Bridge in the Application Interface layer. | No lower layer ever imports from madakit. The bridge is a no-op when madakit is not installed. |
| The Intelligence Bridge accepts any `BaseAgentClient` implementation. It never imports a specific provider. | Provider choice is the caller's decision, not Tessera's. |
| madakit is an optional dependency declared under `[project.optional-dependencies]` in `pyproject.toml`. | Core functionality (publish, fetch, verify) works without madakit installed. |

## 7. Concurrency Model

Tessera is async-first, built on Python's `asyncio`. All I/O — MFP channel communication, disk reads/writes, discovery queries — is non-blocking.

### Per-Swarm Concurrency

Each active swarm runs as an independent `asyncio.Task`. Within a swarm:

| Concern | Mechanism |
|---------|-----------|
| **Incoming messages** | A single receive loop per swarm dispatches incoming MFP messages (tessera responses, HAVE announcements, requests from peers) to the appropriate handler. |
| **Outgoing requests** | The Request Scheduler issues up to `max_concurrent_requests` tessera requests in parallel, each as a separate coroutine. A semaphore bounds concurrency per swarm. |
| **Disk I/O** | File reads (serving tesserae) and writes (assembling) are dispatched to a thread pool via `asyncio.to_thread()` to avoid blocking the event loop. |
| **Peer scoring** | Updated inline on each message receive. No separate task — scoring is a lightweight dict update, not I/O. |

### Cross-Swarm Isolation

Swarms do not share state. A peer participating in three swarms has three independent tasks, three independent bitfields, and three independent Request Schedulers. The only shared resources are:

- The MFP runtime (thread-safe by design)
- The on-disk storage directory (coordinated by file-level locking in the Assembler)
- The Swarm Registry (protected by an `asyncio.Lock`)

### Shutdown

Graceful shutdown cancels all swarm tasks, waits for in-flight tessera writes to complete, closes MFP channels, and unbinds the agent. A configurable shutdown timeout forces termination if draining takes too long.

## 8. Extension Points

Tessera is designed to be extended without modifying its core. The following interfaces are intended for third-party or future customization.

| Extension Point | Interface | Purpose |
|----------------|-----------|---------|
| **Discovery Backend** | `DiscoveryBackend` protocol (Python `Protocol` class) | Plug in alternative discovery mechanisms. The default implementation is a centralized tracker client. A gossip-based or DHT backend can be swapped in by implementing `announce()`, `lookup()`, and `unannounce()`. |
| **Chunking Strategy** | `ChunkingStrategy` protocol | Replace the default fixed-size chunking algorithm. Enables content-defined chunking (e.g., Rabin fingerprinting) for deduplication-sensitive workloads without modifying the Transfer Engine. |
| **Piece Selection Strategy** | `SelectionStrategy` protocol | Replace or augment the default rarest-first algorithm. The Intelligence Bridge uses this interface to inject AI-driven selection when madakit is available. |
| **Storage Backend** | `StorageBackend` protocol | Replace the default filesystem storage. Enables in-memory storage for testing, or alternative backends for embedded deployments where direct filesystem access is unavailable. |
| **Peer Scoring Function** | `ScoringFunction` callable | Customize how peer metrics (latency, failure rate, bytes delivered) are combined into a single score. The default is a weighted linear combination. |
| **Manifest Hooks** | `on_manifest_created`, `on_manifest_received` callbacks | Execute custom logic when a manifest is produced (publish) or first received (fetch). Use cases: logging, content moderation gate, metadata enrichment. |

All extension points use Python's structural subtyping (`typing.Protocol`). No base class inheritance is required. If an object has the right methods with the right signatures, it qualifies.

### Forward Dependencies

| Concern | Owner Spec | Notes |
|---------|-----------|-------|
| **Configuration surface** | ts-spec-010 (API & CLI Design) | A `TesseraConfig` dataclass defines defaults for tessera size, max concurrent requests, max peers per swarm, shutdown timeout, and other configurable values. Other specs reference these values but do not define the config object. |
| **Network partition mid-transfer** | ts-spec-007 (Swarm & Peer Discovery) | Peer unavailability, reconnection, and swarm recovery are Swarm Manager concerns. |
| **MFP crash recovery, partial disk write failures** | ts-spec-011 (Storage & State Management) | Resumable state, write-ahead integrity, and crash recovery belong to the storage layer. |

---

## 9. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Goals G4 (decentralized), G6 (agent-native), G7 (embeddable) that shape the architecture |
| R2 | ts-spec-002 — Glossary | Defines tessera, mosaic, manifest, swarm, and all terms used in this document |
| R3 | ts-spec-003 — Threat Model | Threats T1–T10 and mitigations referenced throughout the data flows and component descriptions |
| R4 | MFP Python Implementation (mirror-frame-protocol) | Public API that defines the MFP boundary |
| R5 | madakit (mada-modelkit) | BaseAgentClient interface that defines the madakit boundary |
| R6 | ts-spec-006 — Content Addressing Spec | Details the Chunker's manifest format and hash tree construction |
| R7 | ts-spec-007 — Swarm & Peer Discovery | Details the Discovery Client backends and Capacity Enforcer limits |
| R8 | ts-spec-008 — Piece Selection & Transfer Strategy | Details the Request Scheduler algorithms and Peer Scorer metrics |
| R9 | ts-spec-009 — AI Integration Spec | Details the Intelligence Bridge's interaction with madakit |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
