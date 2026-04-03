# Glossary

```yaml
id: ts-spec-002
type: spec
status: stable
created: 2026-03-13
revised: 2026-04-04
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [glossary, terminology, tessera]
```

## Table of Contents

1. Tessera-Native Terms
2. Terms Inherited from MFP
3. Terms Inherited from madakit
4. Terms Borrowed from BitTorrent (Redefined)
5. Internal Component Terms
6. References

---

## 1. Tessera-Native Terms

| Term | Definition |
|------|------------|
| **Tessera** | A single piece (chunk) of a file. The atomic unit of transfer between peers. Named after the individual tile in a mosaic. |
| **Mosaic** | A complete file, composed of all its tesserae. A mosaic always represents exactly one file. A mosaic is fully assembled when every tessera has been received and verified. |
| **Manifest** | An immutable metadata document that describes a mosaic: its name, total size, tessera size, hash tree, and any additional attributes. The manifest is the entry point for fetching a file — analogous to a `.torrent` file. Because the manifest hash is the mosaic's identity, any change to the content produces a new manifest and therefore a new mosaic. |
| **Manifest Hash** | The SHA-256 hash of the manifest. The unique, content-addressed identifier for a mosaic. Used for discovery, deduplication, and integrity verification. |
| **Hash Tree** | A Merkle tree whose leaves are the SHA-256 hashes of individual tesserae. The root hash is embedded in the manifest. Enables per-tessera verification without trusting the sender. |
| **Swarm** | The set of peers currently participating in the transfer of a specific mosaic. A peer may belong to multiple swarms simultaneously. |
| **Seeder** | A peer that holds the complete mosaic and serves tesserae to others. |
| **Leecher** | A peer that holds an incomplete mosaic and is actively fetching missing tesserae. A leecher also serves any tesserae it already holds. |
| **Publisher** | The peer that creates the manifest for a mosaic and seeds it for the first time. |
| **Publish** | The act of chunking a file into tesserae, building the hash tree, producing the manifest, and announcing availability to the network. |
| **Fetch** | The act of obtaining a manifest, joining its swarm, downloading all tesserae, verifying them against the hash tree, and assembling the mosaic on disk. |
| **Bitfield** | A bitmap where each bit corresponds to a tessera index and indicates whether the local peer holds that tessera. Exchanged between peers upon joining a swarm and updated via HAVE announcements as new tesserae are acquired. |
| **Watch** | A reactive discovery primitive that polls the manifest index at a configurable interval and fires a callback when new manifests matching structured filters (channel, producer, artifact type) appear. Returns a `WatchHandle` for cancellation. |
| **WatchHandle** | A cancellation handle returned by `watch()`. Call `cancel()` to stop the polling loop. Wraps an `asyncio.Task`. |
| **Reserved Metadata Keys** | A set of conventional metadata key names — `name`, `description`, `channel`, `producer`, `artifact_type`, `supersedes`, `depends_on`, `created_at` — that enable structured filtering via `list_manifests()` and `watch()`. Defined in `tessera.metadata`. Using the reserved keys is optional; when present, they must follow the documented semantics. |

## 2. Terms Inherited from MFP

These terms are defined by the Mirror Frame Protocol. Tessera uses them as-is without redefinition.

| Term | MFP Definition | Role in Tessera |
|------|---------------|-----------------|
| **Agent** | A callable bound to an MFP runtime, identified by an AgentId. | Each Tessera peer is an MFP agent. Peer lifecycle maps to agent bind/unbind. |
| **AgentId** | 32-byte runtime-assigned cryptographic identifier. | The peer's identity in every swarm it joins. |
| **Channel** | An encrypted, bidirectional communication link between two agents. | Each peer-to-peer connection in a swarm is an MFP bilateral channel. |
| **ChannelId** | 16-byte channel identifier. | Used internally to route tessera requests and responses between specific peers. |
| **Runtime** | The central coordinator that manages agents, channels, and the message pipeline. | A Tessera node runs inside an MFP runtime. |
| **Frame** | An ordered sequence of cryptographic blocks that wraps every protocol message. | Tessera messages (requests, tesserae, announcements) are framed by MFP before transmission. |
| **Ratchet** | State that advances with every message, invalidating old frames. | Prevents replay of stale tesserae or manifests. |
| **Quarantine** | Isolation of an agent that exceeds rate limits or fails validation. | Malicious peers (piece poisoning, flooding) are quarantined by MFP automatically. |
| **Federation** | Cross-runtime communication via bilateral channels over TCP. | Enables swarms that span multiple MFP runtimes on different machines. |
| **Bilateral Channel** | A channel between agents in different runtimes, bootstrapped via key exchange. | The transport layer for federated swarms. |

## 3. Terms Inherited from madakit

These terms are defined by madakit. Tessera uses them when the AI integration layer is active.

| Term | madakit Definition | Role in Tessera |
|------|-------------------|-----------------|
| **Provider** | A backend that executes LLM requests (cloud API, local server, or native engine). | Powers content discovery queries, intelligent piece selection, and content moderation. |
| **Middleware** | A composable wrapper around a provider that adds cross-cutting behavior. | Tessera stacks middleware for retry, circuit breaking, cost control, and caching on AI operations. |
| **BaseAgentClient** | The single abstract interface that all providers and middleware implement. | Tessera's AI layer interacts exclusively through this interface — no provider lock-in. |
| **AgentRequest / AgentResponse** | The standard request and response types for LLM interactions. | Used when Tessera queries an LLM for content search, peer ranking, or moderation decisions. |

## 4. Terms Borrowed from BitTorrent (Redefined)

These terms originate from the BitTorrent protocol. Tessera borrows the concepts but redefines them to fit its security model and architecture.

| Term | BitTorrent Meaning | Tessera Redefinition |
|------|-------------------|----------------------|
| **Piece** | A fixed-size chunk of a file, identified by index and verified by SHA-1 hash. | Replaced by **tessera**. Same concept but verified via SHA-256 within a Merkle hash tree, and always transmitted inside an MFP-encrypted channel. |
| **Tracker** | A centralized HTTP/UDP server that maps info_hashes to peer IP:port lists. | Tessera's equivalent is the **discovery service** — a component that maps manifest hashes to peer AgentIds. May be centralized, gossip-based, or hybrid. Not yet specified (see ts-spec-007). |
| **Swarm** | The set of all peers sharing a specific torrent, including seeders and leechers. | Same concept, retained. In Tessera, every swarm member is an authenticated MFP agent — there are no anonymous participants. |
| **Seeder / Leecher** | Seeder has the complete file; leecher is still downloading. | Same concept, retained. In Tessera, both roles are MFP agents with cryptographic identity. A leecher serves tesserae it already holds. |
| **Info Hash** | SHA-1 hash of the torrent's info dictionary. The unique identifier for a torrent. | Replaced by **manifest hash** (SHA-256). Serves the same purpose — content-addressed identifier for a mosaic. |
| **Bitfield** | A bitmap where each bit indicates whether the peer holds the corresponding piece. | Same concept, retained. Exchanged between peers over MFP channels upon joining a swarm. |
| **Rarest First** | Piece selection strategy that prioritizes pieces held by the fewest peers. | Same concept, applicable. Tessera may also layer AI-driven selection on top (see ts-spec-008, ts-spec-009). |
| **Endgame Mode** | Strategy where remaining pieces are requested from all available peers to avoid slow completion. | Same concept, applicable. Specified in ts-spec-008. |

## 5. Internal Component Terms

These terms name subcomponents defined in ts-spec-004 (System Architecture). They are not protocol-level concepts visible to external callers — they describe internal modules within Tessera's layered architecture.

### Transfer Engine Components

| Term | Definition |
|------|------------|
| **Chunker** | Splits a file into tesserae of configured size, builds the Merkle hash tree, and produces the manifest. Used during publish. |
| **Assembler** | Writes verified tesserae to their position on disk, detects completion, and performs the final whole-file hash check. Used during fetch. |
| **Piece Verifier** | Hashes each received tessera and validates it against the corresponding Merkle tree leaf. Rejects mismatches immediately. |
| **Request Scheduler** | Decides which tesserae to request from which peers. Implements rarest-first selection, endgame mode, and concurrent request limits. Accepts hints from the Intelligence Bridge when available. |
| **Peer Scorer** | Tracks per-peer metrics (serve latency, failure rate, bytes delivered) and feeds scores to the Request Scheduler for prioritization and to the Swarm Manager for disconnect decisions. |
| **Bitfield Manager** | Maintains the local bitfield, exchanges bitfields with peers on channel establishment, and processes HAVE announcements. |

### Swarm Manager Components

| Term | Definition |
|------|------------|
| **Swarm Registry** | Maps manifest hashes to active swarms. Tracks membership, capacity, and state for each swarm. |
| **Peer Connector** | Establishes and tears down MFP channels with peers. Handles the join handshake (manifest hash exchange, bitfield swap). |
| **Discovery Client** | Queries discovery backends to find peers for a given manifest hash. Supports multiple backends and cross-references results when several are active (T8 mitigation). |
| **Capacity Enforcer** | Enforces maximum peer count per swarm and maximum swarm count per node. Rejects new joins when limits are reached (T4 mitigation). |

### Application Interface Components

| Term | Definition |
|------|------------|
| **Intelligence Bridge** | Optional adapter that connects madakit's `BaseAgentClient` to the Request Scheduler and Discovery Client. When madakit is not installed, this component is a no-op. |

---

## 6. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Establishes goals, non-goals, and naming conventions used throughout this glossary |
| R2 | MFP Python Implementation (mirror-frame-protocol) | Source of all MFP-inherited terms |
| R3 | madakit (mada-modelkit) | Source of all madakit-inherited terms |
| R4 | BitTorrent Protocol Specification (BEP 3) | Source of borrowed and redefined terms |
| R5 | ts-spec-007 — Swarm & Peer Discovery | Further specifies the discovery service term |
| R6 | ts-spec-008 — Piece Selection & Transfer Strategy | Further specifies rarest first, endgame mode, and bitfield usage |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
