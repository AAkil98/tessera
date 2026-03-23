# Vision & Scope

## 1. Problem Statement

Peer-to-peer file sharing remains split between two unsatisfying extremes. Public torrent networks offer decentralized transfer but provide no peer authentication, no payload encryption, and no defense against poisened pieces or sybic participants. Private sharing solutions (cloud drives, managed transfer services) solve trust but reintroduce centralization, single points of failure, and vendor lock-in.

Neither model was designed for a world where autonomous agents — not just humans — initiate, negotiate, and execute file transfers. Agents face additional threats that traditional P2P ignores: prompt injectiom embedded in metadata, replay of stale manifests to trick an agent into re-downloading obsolete content, and forged peer announcements that redirect transfers to adversial nodes.

There is no existing system that combines decentralized swarm-based transfer with cryptographuc peer identity, end-to-end chunk encryption, anti-replay guarantees, and an AI-augmented intelligence layer — all as a single coherent protocol rather than boldted-on afterthoughts.

mada-swarm exists to fill that gap.

## 2. Vision

mada-swarm is a secure, agent-native, swarm-based file sharing protocol where every peer is cryptographically identified, every chunk is encrypted end-to-end, and intelligence is a first-class layer — not an afterthought.

A human or agent publishes a file. The system chunks it, builds a hash tree, and produces a manifest. Peers discover the manifest, join the swarm, and exchange pieces over MFP bilateral channels — each transfer authenticated, encrypted, and replay-proof by the protocol itself, not by application code. madakit sits above the swarm, providing intelligent piece selection, natural-language content discovery, and automated moderation.

The result is a system that inherits the resilience of decentralized swarms, the security posture of MFP, and the adaptability of AI-driven middleware — unified under a single protocol with a minimal, composable API.

### Goals & Non-Goals

- **G1: Authenticated swarm.** Every peer in a swarm is bound to a cryptographic identity via MFP. No anonymous participation.
- **G2: End-to-end chunk encryption.** Piece data is encrypted in transit between peers. Intermediaries and transport layers never see plaintext.
- **G3: Anti-replay and anti-forgery.** MFP's temporal ratchet ensures stale or forged pieces and manifest are rejected at the protocol layer, before application logic runs.
- **G4: Decentralized transfer.** Files are sourced from multiple peers simultaneously. No single peer is required to hold the complete file.
- **G5: AI-augmented operations.** Content discovery, and moderation are driven by LLM capabilities via madakit.
- **G6: Agent-Native API.** The protocol is designed to be invoked by autonomous agents as naturally as by human users.
- **G7: Composable and embeddable.** mada-swarm is a library first. It can be embedded in any Python process or run a standalone daemon.

### Non-Goals

- **NG1: BitTorrent Compatibility.** We do not implement or interoperate with the BitTorrent protocol, DHT, or tracker standards.
- **NG2: Anonymity.** Authenticated identity is a core guarantee. Anonymizing the network is an explicit non-goal.
- **NG3: Massive-scale public swarms.** The design targets private or semi-private networks of tens to hundreds of peers, not open internet swarms of thousands.
- **NG4: Streaming media.** Real-time audio/video streaming is out of scope. The unit of transfer is a complete file.
- **NG5: Storage platform.** mada-swarm moves files between peers. It is not a distributed filesystem or persistent object store.

---

## Target Users

- **Agent developers** building autonomous systems that need to exchange files securely without trusting a central broker. Their agents bind to mada-swarm as MFP agents and participate in swarms programmatically.
- **Small-team operators** running private infrastructure (research labs, internal tooling groups, edge deployments) who need decentralized file distribution with auditability and encryption — without the overhead of enterprise file sync platforms.
- **Mada ecosystem users** already running MFP runtimes or madakit stacks, for whom mada-swarm is a natural extension — adding file transfer capability to an environment that alread handles secure agent communication and AI orchestration.

---

## Core Value Proposition

- **Security by default, not by configuration.** Peer authentication, chunk encryption, and replay prevention are protocol guarantees — they cannot be misconfigured or skipped. This is inherited from MFP's design, where validation happens before payloads reach application code.
- **Zero-trust peer model.** Every piece received is hash-verified against the manifest. Every message is cryptographically bound to its sender. Malicious peers are quarantined automatically via MFP's rate limiting and quarantine mechanisms. Trust is proven, never assumed.
- **Intelligence as a layer.** AI capabalities (content discovery, smart peer selection, moderation) are delivered through madakit's composable middleware stack. They can be swapped, stacked, or removed without touching the transfer protocol. The swarm works without AI; AI makes it smarter.
- **Embeddable by design.**mada-swarm is a Python library, not a monolithic application. An agent can join a swarm, fetch a file, and leave — in a few lines of code, inside any process.

---

## Dependency Rationale

**Mirror Frame Protocol (MFP)**

mada-swarm does not implement its own transport, encryption or peer identity. MFP provides all three:

**Need:** Peer identity
**MFP Capability:** AgentID — 32-byte cryptographically bound identifier

**Need:** Encrypted channels
**MFP Capability:** Bilateral channels with ChaCha2-Pli1305 AEAD

**Need:** Anti-replay
**MFP Capability:** Temporal ratchet — each messages advances state, old framed are permantently invalid

**Need:** Peer lifecycle
**MFP Capability:** bind/unbind with quarantine for misbehaving peers

**Need:** Wire format
**MFP Capability:**64-byte envelope header with federation transport over TCP

**Need:** Connection management
**MFP capability:** Connection pooling, circuit breakers, timeouts.

Building these from scratch would represent the majority of the project's complexity. MFP delivers them as a tested, production-hardened library.

**madakit**

madakit provides the AI/LLM interface layer. mada-swarn uses it for capabilities that benefit from language model reasoning:

| **Need** | **madakit capability** |
| --- | --- |
| Content discovery | Natural-language queries routed to any of 21 LLM providers |
| Smart peer selection | LLM-driven ranking via composable middleware |
| Content moderation | ContentFilterMiddleware for safety checks before sharing |
| Resilience | RetryMiddleware, CircuitBreakerMiddleware, FallbackMiddleware |
| Cost control | CostControlMiddleware with budget limits and alerts |

madakit is an optional enhancement. The core transfer protocol functions without it. When present, it is accessed exclusively through its `BaseAgentClient` interface — no provider lock-in.

---

# Glossary

## Tessera-Native Terms

| **Term** | **Definition** |
| --- | --- |
| **Tessera** | A single piece (chunk) of a file. The atomic unit of transfer between peers. Named after the individual tile in a mosaic |
| **Mosaic** | A complete file, composed of all its tesseras. A mosaic is fully assembled when every tessera has been received and verified |
| **Manifest** | A metadata document that describes a mosaic: its name, total size, tessera size, hash tree, and any additional attributes. The manifest is the entry point for fetching a file — analogous to a `.torrent` file. |
| **Manifest Hash** | The SHA-256 of the manifest. The unique, content-addressed identifier for a mosaic. Used for discovery, deduplication, and integrity verification |
| **Hash Tree** | A Merkle treee whose leaves are the SHA-256 hashes of individual tesserae. The root hash is embedded in the manifest. Enables per-tessera verification without trusting the sender. |
| **Swarm** | The set of peers currently participating in the transfer of a specific mosaic. A peer may belong to multiple swarms simultaneously. |
| **seeder** | A peer that holds the complete mosaic and serves tesserae to others. |
| **Leecher** | A peer that holds an incomplete mosaic and is actively fetching missing tesserae. A leecher also serves any tesserae it already holds. |
| **Published** | The peer that creates the manifest for a mosaic and seeds it for the first time |
| **Publish** | The act of chunking a file into tesserae, building the hash tree, producing the manifestm and announcing availability to the network |
| **Fetch** | The act of obtaining a manifest, joining its swarm, downloading all its tesserae, verifying them against the hash tree, and assembling the mosaic on disk. |

## Terms Inherited from MFP

These terms are defined by the Mirror Frame Protocol. Tessera uses them as-is without redefinition.

| **Term** | **MFP Definition** | **Role in Tessera** |
| --- | --- | --- |
| **Agent** | A callable bound to an MFP runtime, identified by AgentId. | Each tessera peer is an MFP agent. Peer lifecycle mapts to agent bind/unbind |
| **AgentID** | 32-byte runtime-assigned cryptographuc identifier. | The peer's identity in every swarm it joins. |
| **Channel** | An encrypted, bidirectional communication link between two agents. | Each peer-to-peer connection in a swarm is an MFP bilateral channel. |
| **ChannelId** | 16-byte channel identifier. | Used internally to route tessera requests and responses between specific peers. |
| **Runtime** | The central coordinator that manages agents, channels, and the message pipeline. | A Tessera node runs inside an MFP runtime |
| **Frame** | An ordered sequence of cryptographic blocks that wraps every protocol message. | Tessera messages (requests, tesseraem announcements) are framed by MFP before transmission |
| **Ratchet** | State that advances with every message, invaliding the old frames. | Prevents replay of old stale tesserae or manifests. |
| **Quarantine** | Isolation of an agent that exceeds rate limits or fails validation. | Malicious peers (piece poisoning, flooding) are quarantined by MFP automatically. |
| **Federation** | Cross-runtime communication via bilateral channels over TCP. | Enables swarms that span multiple MFP runtimes on different machines |
| **Bilateral Exchange** | A channel between agents in different runtimes, boostrapped via key exchange | The transport layer for federated swarms |

---

## Terms Inherited from madakit

These terms are defined by madakit. Tessera uses them when the AI integration layer is active.

| **Term** | **madakit definition** | **Role in Tessera** |
| --- | --- | --- |
| **Provider** | A backend that executes LLM requests (cloud API, local server, or native engine) | Powers content discovery queries, intelligent piece selection and content moderation |
| **Middleware** | A composable wrapper around a provider that adds cross-cutting behavior. | Tessera stacks middleware for retry, circuit breaking, cost control, and caching on AI operations. |
| **BaseAgentClient** | The single abstract interface that all provideers and middleware implement | Tessera's AI layer that interacts exclusively through this interface — no provider lock-in |
| **AgentRequest / AgentResponse** | The standard request and response types for LLM interactions | Used when Tessera queries an LLM for content search, peer ranking, or moderation decisions |

---

## Terms Borrowed from BitTorrent

These terms originate from the BitTorrent protocol. Tessera borrows the concepts but redefines them to fits its security model and architecture.

| **Term** | **BitTorrent Meaning** | **Tessera Definition** |
| --- | --- | --- |
| **Piece** | A fixed-size chunk of a file, identified by index and verified by SHA-1 hash. | Replayed by **tessera**. Same concept but verified via SHA-256 within a Merke hash tree, and always transmitted inside an MFP-encrypted channel. |
| **Tracker** | A centralized HTTP/UDP server that maps info_hashes to peer IP:port lists. | Tessera's equivalent is the **discovery service** — a component that maps manifest hashes to peer AgentIds. May be centralized, gossip-based, or hybrud. Not yet specified. |
| **Swarm** | The set of all peers sharing a specific torrent, including seeders and leechers. | Same concept retained. In Tessera, every swarm member is an authenticated MFP agent — there are no anonymous participant |
| **Seeder / Leecher** | Seeder has the complete file; the leecher is still downloading | Same concept, retained. In Tessera, both roles are MFP agents with cryptographic identity. Leecher serves tesserae it already holds. |
| **Info Hash** | SHA-1 hash of the torrent's info dictionary. The unique identifier for a torrent. | Replaced by **manifest** hash (SHA-256). Serves the same purpose — content-addressed identifer for a mosaic |
| **BitField** | Piece selection strategy that prioritizes pieces held by the fewest peers. | Same concept, applicable. Tessera may also layer AI-drive selection on top |
| **Endgame mode** | Strategy where remaining pieces are requested from all available peers to avoid slow comptetion. | Same concept applicable. |

---

# Threat Model

## Trust Assumptions

Tessera's security model rests on the following assumptions. If any of these are violated, the guarantees described in this document do not hold.

| **Assumption** | **Rationale** |
| --- | --- |
| **The runtime is trusted** The runtime that hsots tessera peers is part of the trusted computing base. It correcly executes the message pipeline, enforces quarantine and does not leak material. | Inherited from MFP. Tessera cannot protect against a compormised runtime any more than an application can protect against a compromised OS kernel. |

---

# System Architecture

## Architecture Overview

Tessera is organized as four layers stacked on top of two external dependencies. Each layer has a single responsibility and communicates only with its immediate neighbor.

From bottom to top:

- **MFP Runtime (External)** — Provides peer identity, encrypted channels, message pipeline, and federation transport. Tessera never touches raw sockets or cryptographic primitives directly.
- **Transfer Engine** — Manages tessera exchange: piece requests, bitfields negotations, hash verification, peer scoring, and reassembly. This is the core of Tessera.
- **Swarm manager** — Manages swarm lifecycle: joining, leaving, peer tracking, capacity enforcement, and discovery service interaction.
- **Application Interface** — The public API and CLI that humans and agents use to publish, fetch, and query mosaics.
- **Intelligence Layer** (Optional, external) — madakit middleware for content discovery, smart selection, and moderation. Accessed through the Application Interface; never coupled to lower layers.

Each layer is a Python module with an explicit public interface. No layer imports from a layer above it. The Transfer Engine and Swarm Manager together form Tessera's core — they contain all protocol logic that is neither inherited from MFO nor optional via madakit.

## Component Description

### Transfer Engine

The Transfer Engine is responsible for moving tesserae between peers and guaranteeing that every piece matches the manifest.

| **Subcomponent** | **Responsibility** |
| --- | --- |
| **Chunker** | Splits a file into tesserae of configured size. Builds the Merkle hash tree. Produces the manigest. Used during publish. |
| **Assembler** | Writes verified tesserae to their position on disk. Detects completion. Performs final whole-file hash check. Used during fetching. |
| **Piece Verifier** | Hashes each received tessera and validates it against the corresponding leaf in the hash tree. Rejects mismatches immediately. |
| **Request scheduler** | Decides which tesserae to request from which peers. Implements rarest-first selection, endgame mode, and concurrent request limits. Accept hints from the Intelligence Layer when available. |
| **Peer Scorer** | Tracks per-peer metrics: serve latency, failure rate, bytes delivered. Feeds scores to the Request Scheduler for prioritization and to the Swarm Manager for disconnect decisions |
| **Bitfield Manager** | Maintains the local bitfields (which tesserae this peer holds). Exchanges bitfields with peers on channel establishment. Processes HAVE announcments. |

### Swarm Manager

The Swarm Manager is responsible for the set of peers participating in a mosaic's transfer.

| **Subcomponent** | **Responsibility** |
| --- | --- |
| **Swarm Registry** | Maps manifest hashes to active swarms. Tracks membership, capacity, and state for each swarm. A peer may be registered in multiple swarms |
| **Peer Connector** | Establishes and tears down MFP channels with peers. Handles the join handshake (manifest hash exchange, bitfield swap) |
| **Discovery client** | Queries the discovery service to find peers for a given manifest hash. Supports multiple discovery backends (centralized, gossib, manual). Cross-referecnes results when multiple sources are available |
| **Capacity Enforcer** | Enforces maximum peer count per swarm and maximum swarm count per node. Rejects new joins when limits are reached. |

### Application Interface

The Application Interface is the boundary between Tessera internals and the outside world.

| **Subcomponent** | **Responsibility** |
| --- | --- |
| **Public API** | Python functions: `publish()`, `fetch()`, `query()`, `status()`, `cancel()`. The library entry point. Designed for both human callers and agent callers. |
| **CLI** | Command-line wrapper around the public API. Provides tessera `tessera publish`, `tessera fetch`, `tessera status`, etc. |
| **Intelligence Bridge** | Optional adapter that connects madakit's `BaseAgentClient` to the Request scheduler and discovery client. When madakit is not installed, this component is no-op. |

## Dependency Boundaries

Tessera enforces strict boundareis with its two external dependencies. These rules ensure that swapping, upgrading, or removing a dependency does not ripple through the codebase.

**MFP Boundary**

| **Rule** | **Rationale** |
| --- | --- |
| Tessera imports only from `mfp`'s public API: `Runtime`, `RuntimeConfig`, `bind`, `unbind`, `mfp_send`, `mfp_channels`, `mfp_status`, `AgentHandle`, `AgentId`, `ChannelId`, `ChannelInfo`, `Receipt`. | No coupling to MFP internals (pipeline stages, storage engine, ratchet state) |
| Tessera never constructs `Frame`, `Block`, `StateValue`, or `ProtocolMessage` objects directly | Frame construction is MFP's responsibility. Tessera treats the channel as an opaque encrypted pipe. |
| Tessera never calls MFP's cryptographic primitives (`hmac_sha256`, `chacha20`) for its purposes. It uses Python's `hashlib.sha256` for tessera hashing | Keeps Tessera's crypto needs (content hashing) separate from MFP's crypto needs (channel encryption). Avoids tight coupling to MFP's `cryptography` library version |

**madakit boundary**

| **Rule** | **Rationale** |
| --- | --- |
| All madakit access goes through the Intelligence Bridge in the Application Interface layer | No lower layer ever imports ever impors from madakit. The bridge is a no-op when madakit is not installed. |
| The intelligence Bridge accepts any `BaseAgentClient` implementation. It never imports a specific provider. | Provider choice is the caller's decision, not Tessera's |
| madakit is an optional dependecy declared under `[project.optional-dependencies]` in `pyproject.toml` | Core functionality (publish, fetch, verify) works without madakit installed |

## Concurrency Model

Tessera is async-first, built on Python's `asyncio`. All I/O — MFP channel communication, disk reads/writes, discovery quereis — is non-blocking.

**Per-swarm activity**

Each active swarm runs as an independent `asyncio.Task`. Within a swarm:

| **Concern** | **Mechanism** |
| --- | --- |
| **Incoming Message** | A single receive loop per swarm dispatches incoming MFP messages (tessera responses, HAVe announcements, requests from peers) to the appropriate handler. |
| **Outgoing Requests** | The Request Scheduler issues up to `max_concurrent_requests` tessera requests in parallel, each as a separate coroutine. A semaphore bounds concurrency per swarm. |
| **Disk I/O** | File reads (serving tesserae) and writes (assembling) are dispatched to a thread pool via `asyncio.to_thread()` to avoid blocking the event loop. |
| **Peer scoring** | Updated inline on each message receive. No separate task — scoring is a lightweight dict update, not I/O. |

**Cross-Swarm Isolation**

Swarms do not share state. A peer participating in three swarms has three independent tasks, three independent bitfields, and three independent Request Schedulers. The only shared resources are:

- The MFP runtime (thread-safe by design)
- The on-disk storage directory (coordinated by file-level locking in the Assembler)
- The Swarm Registry (protected by `asyncio.Lock`)

**Shutdown**

Graceful shutdown cancels all swarm tasks, waits for in-flight tessera writes to complete, closes MFP channels, and unbinds the agent. A configurable shutdown timeout forces termination if draining takeas too long.

## Extension Points

Tessera is designed to be extended without modifying its core. The following interfaces are intended for third-party or future customization.

| **Extension Point** | **Interface** | **Purpose** |
| --- | --- | --- |
| **Discovery Backned** | `DiscoveryBackend` protocol (Python `Protocol` class) | Plug in alternative discovery mechanisms. The default implementation is a centralized tracker client. A gossip-based or DHT backend can be swapped in by implementing `announce()`, `lookup()`, `unannounce()` |
| **Piece Selection Strategy** | `SelectionStrategy` protocol | Replace or augment the default rarest-first algorithm. The Intelligence Bridge uses this interface to inject AI-driven selection when madakit is available |
| **Storage Backend** | `StorageBackend` | Replace the default filesystem storage. Enables in-memory storage for testing, or alternative backends for embedded deployments where direct filesystem is unavailable |
| **Peer Scoring Function** | `ScoringFunction` callable | Customize how peer metrics (latency, failure rates, bytes delivered) are combined into a single score. The default is a weighted linear combination. |
| **Manifest Hooks** | `on_manifest_created`, `on_manifest_received` callbacks | Execute custom logic when a manifest is produced (publish) or first received (fetch). Use cases: logging, content moderation gate, metadata, enrichment |

All extension points use Python's structural subtyping (`typing.Protocol`). No base class inheritance is required. If an object has the right methods with the right signatures, it qualifies.

---

# Wire Protocol Addendum

## Purpose & Scope

This document defines the application-layer message format that Tessera peers exchange over MFP channels. IT is an addendum to MFP's wire protocol, not a replacement — MFP owns the transport envelope, encryption, and frame structure; Tessera owns the plaintext payload inside.

**What MFP provides**

MFP delivers every Tessera message through a pipeline that is fully transparent to this spec:

| **Concern** | **MFP Mechanism** |
| --- | --- |
| Wire framing | 64-byte envelope header + symmetric frame pair |
| Payload encryption | AES-256-GCM nonce derived from channel ID and step counter |
| Authentication | Frame binding via HMAC-SHA256; sender identity proven by key possession |
| Replay protection | Monotonic step counter advanced by temporal ratchet |
| Channel Management | `establish_channel()`, `mfp_send()`, `mfp_channels()` |

From MFP's perspective, every Tessera message is an opaque `bytes` payload passed to `mfp_send()`. MFP encrypts, frames, transmits, validates, decrypts, and delivers it — without inspecting or interpreting the contents.

**What this spec defines**

This document specifies the structure inside that opaque payload:

- **Message type discrimination.** A type tag that tells the receiver how to interpret the remaining bytes.
- **Field layouts.** The serialization format from each type — handshake, bitfield, request, piece, have, cancel, and reject.
- **Message flow sequences.** The expected order of messages during swarm join, piece exchange, and endgame.
- **Payload size constraints.** How tessera size, manifest size, and MFP's `max_payload` (default to 1 MB, hard limit 10 MB) interact.
- **Error and rejection semantics.** Protocol-level error codes and their meaning.
- **Extensibility.** How new message types can be introduced without breaking existing peers.

## Relationship to MFP Wire Format

Tessera messages occupy a single layer in MFP's protocol stack. Understanding where Tessera sits — and what it must never touch — is essential to the rest of this spec.

**Message nesting**

A Tessera message on the wire is nested inside MFP's envelope.

**One Tessera message per MFP message**

Each call to `mfp_send(handle, channel_id, payload)` carries exactly one Tessera message. Tessera does not batch multiple messages into a single MFP payload and does not split a single message across multiple MFP sends. This simplifies framing — the Tessera message boundary is always the MFP message boundary.

**What Tessera inherits for free**

Because every Tessera message travel an MFP frame, the following properties hold without any Tessera-side implementation

| **Property** | **Guarantee** |
| --- | --- |
| **Confidentiality** | Payload is AES-256-GCM encrypted. Network observes see ciphertext only |
| **Integrity** | GCM authentication tag detects any modification in transit |
| **Authentication** | The sender's identity (AgentID) is cryptographically bound to the channel. A forged sender cannot produce valid frame. |
| **Replay protection** | The ratchet's monotonic step counter ensures each frame is unique. Replayed frames are rejected before encyption |
| **Ordering** | Step counter provide a total order per channel. Out-of-order delivery is detectable. |
| **Peer isolation** | Each channel is an independent encrypted pipe. Messages on channel A are invisible to peers on channel B |

**What Tessera must handle itself**

MFP is message-type-agnostic. The following are Tessera's responsibility:

| **Concern** | **Tessera's job** |
| --- | --- |
| **Message type dispatch** | Interpret the `msg_type` byte and route to the correct handler |
| **Field parsing** | Deserialize the message body according to the type-specific layout |
| **Semantic Validation** | Reject messages that are syntactically valid but semantically wrong (e.g., a REQUEST for a tessera index beyond the manifest's range) |
| **State Machine Enforcement** | Ensure messages arrive in a valid order (e.g., handshake before bitfield before request) |
| **Application-level errors** | Generate and handle REJECT messages for protocol violations that MFP cannot detect. |

## Message Types

Tessera defines eight message types. Each is identified by a single-byte `msg_type` tag at offset 0 of the plaintext payload.

**Type registry**

| **msg_type** | **Name** | **Direction** | **Purpose** |
| --- | --- | --- | --- |
| `0x01` | HANDSHAKE | Bidirectional | Initiate a peer session. Exchange manifest hash and protocol version |
| `0x02` | BITFIELD | Bidirectional | Declare which tesserae the sender currently holds. Sent once, immediately after HANDSHAKE |
| `0x03` | REQUEST | Fetcher -> seeder | Request one or more tesserae by index |
| `0x04` | PIECE | Seeder -> Fetcher | Deliver a single tessera payload with its index and hash |
| `0x05` | HAVE | Bidirectional | Announce that the sender has acquired a new tessera. Sent after successful verification of a received piece |
| `0x06` | CANCEL | Fetcher -> Seeder | Cancel a previously sent REQUEST. Used during endgame mode to suppress duplicate deliveries |
| `0x07` | REJECT | Bidirectional | Refuse a message with an error code. Used for protocol violations, capacity limits, and invalid requests. |
| `0x08` | KEEP_ALIVE | Bidirectional | Indicate the peer is still active. Carries no body. Sent when no other message has been sent within the keep-alive interval. |

Type values `0x00` and `0x09-0x7F` are reserved for future Tessera protocol use. Values `0x80-0xFF` are reserved for extension messages.

**State machine rules:**

1. The first message on any channel must be HANDSHAKE. Any other message type received before a completed handshake triggers a REJECT with `UNEXPECTED_MSG` and channel closure.
2. After both peers have exchanged HANDSHAKE, each peet meet must send exactly one BITFIELD. No REQUEST, PIECE, or HAVE may be sent before both bitfields are exchanged.
3. Once bitfields are exchanged, the channel enters the **transfer phase**. REQUEST, PIECE, HAVE, CANCEL, REJECT, and KEEP_ALIVE may be sent in any order.
4. A second HANDSHAKE or BITFIELD on an already-established channel trigers a REJECT with `DUPLICATE_MSG`.

**Message descriptions**

- **HANDSHAKE** — Establishes the shared context for the channel. Both peers must agree on the manifest hash; a mismatch means they are not in the same swarm, and the channel is cosed. The protocol version field allows peers to detect incompatible implementation early.

- **BITFIELD** — A compact representation of the sender's tessera inventory. Each bit at position i indicates whether sender holds tessera i. The bitfield length is derived from the manifest's tessera count (exchanged or known via the manifest). A seeder sends all ones-bitfield; a fresh leecher sends all zeros.

- **REQUEST** — Asks the peer to send one or more tesserae. Each request specifies a tessera index. The Request Scheduler (ts-spec-004) decides which indices to request and from which peers. A peer may have multiple outstanding requests on the same channel, bounded by the configured concurrency limit.

- **PIECE** — Carries the raw bytes of a single tessera along with its index. The receiver hashes the payload and verifies it against the manifest's hash tree (Piece Verifier). On mismathc, the receiver sends a REJECT with `HASH_MISMATCH` and scores the peer down.

- **HAVE** — a lightweight announcement that the sender now holds a tessera it previously did not. Sent immediately after a tessera is verified and written to disk. Peers update their internal view of the sender's bitfield accordingly.

- **CANCEL** — withdraws a previously issued REQUEST. Primarily used in endgame mode, where the tessera is requested from multiple peers. Once any peer delivers it, the fetcher cancels the redundant requests to avoid wasting bandwidth.

- **REJECT** — A structured error response. Carries an error code and the `msg_type` of the rejected message. May optionally include the request context (e.g., the tessera index that was refused).

- **KEEP ALIVE** — A zero-body heartbeat. Prevents MFP from treating an idle channel as dead. The keep-alive internal is configurable; the default is 30 seconds.

## Message Encoding

All tessera messages use a binary encoding with big-endian byte order. No self-describing serialization framework (protobuf, msgpack, JSON) is used — the format is hand-specified for compactness and zero-copy parsing.

**Common header**

Every tessera message begins with a 1-byte type tag:

| **Offset** | **Size** | **Field** |
| --- | --- | --- |
| 0 | 1 | msg_type |
| 1 | ... | message body (type-specific) |

**Field type conventions**

| Notation | Meaning |
| --- | --- |
| `u8` | Unsigned 8-bit integer |
| `u16` | Unsigned 16-bit integer, big-endian |
| `u32` | Unsigned 32-bit integer, big-endian |
| `u64` | Unsigned 64-bit integer, big-endian |
| `bytes(n)` | Fixed-length byte sequence of exactly n bytes |
| `bytes(*)` | Variable-length byte sequence consuming all remaining bytes in the message |
| `bits(n)` | bitfields of n bits, padded to the next byte boundary with trailing zeros |

**Per-type layouts**

**HANDSHAKE (0x01)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type = 0x01 |
| 1 | 2 | version Protocol version (currenntly 0x0001) |
| 3 | 32 | manifest_hash | SHA-256 of the manifest this peer wants to exchange |
| 35 | 4 | tessera_count | Total number of tesserae in the mosaic (u32) |

Total: 43 bytes (fixed)/

The `tessera_count` and `tessera_size` fields allow the receiver to validate the subsequent BITFIELD length and to sanity-check incoming PIECE payloads before obtaining the full manifest. The final tessera may be smaller than `tessera_size` — this is implicit and does not require a separate field.

**BITFIELD (0x02)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type = 0x02 |
| 1 | [count/8] | bitfield  one bit per tessera, MSB-first, trailing bits zero-padded |

Total: 1 + [tessera_count / 8] bytes.

Bit i (counting from 0, MSB of first byte = index 0) is 1 if the sender holds tessera i, `0` otherwise. For a mosaic with 1000 tesserae, the bitfield is 125 bytes. For a 4GB file at 256 KB tessera size (16,384 tesserae), the bitfield is 2,048 bytes — well within MFP's payload limit.

**REQUEST (0x03)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type    = 0x03 |
| 1 | 4 | index       Tessera index being requested (u32) |

Total: 5 bytes (fixed).

One REQUEST message per tessera. Batching multiple indices into a single message was considered and rejected — individual messages simpligy cancellation (one CANCEL per REQUEST) and allow MFP\s per-message ordering to naturally sequence requests.

**PIECE (0x04)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type =      0x04 |
| 1 | 4 | index           Tessera index (u32) |
| 5 | bytes(*) | data     Raw tessera bytes |

Total: 5 + tessera_data_length bytes

The receiver knows the expected length from the manifest (all tesserae are `tessera_size` except potentially the last). The hash is not included in the message — the receiver computes SHA-256 over `data` and verifies against the manifest's hash tree independently. Including the hash would let a poisoner pre-compute a "matching" pair; omitting it forces verification against the trusted manifest.

**HAVE (0x05)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type      = 0x05 |
| 1 | 4 | index         Tessera index now held (u32) |

Total: 5 bytes (fixed).

**CANCEL (0x06)**

| Offset | Size | Field |
| 0 | 1 | msg_type = 0x06 |
| 1 | 4 | index     Tessera index to cancel (u32) |

Total: 5 bytes (fixed).

A CANCEL for an index that was never requested or has already been served is silently ignored — it is not an error.

**REJECT (0x07)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type = 0x07 |
| 1 | 1 | rejected_type   msg_type of the message being rejected |
| 2 | 2 | error_code      Error code (u16) |
| 4 | 4 | context         Optional contex (u32). For REQUEST/PIECE rejections, this is the tessera index. Zero if not applicable |

Total: 8 bytes (fixed).

**KEEP_ALIVE (0x08)**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_type  = 0x08 |

Total: 1 byte (fixed). No body.

---

## Message Flow Diagrams

This section illustrates the three primaty interaction patterns between Tessera peers. Each diagram shows the Tessera-layer messages only — MFP framing, encryption, and channel bootstrap are implicit.

### Swarm Join

---

## Payload Size Constraints

Tessera messages ride inside MFP payloads. MFP enforces size limits at the transport layer; Tessera must stay within those bounds and impose its own application-layer constraints.

**MFP Limits**

| **Limit** | **Value** | **Source** |
| --- | --- | --- |
| Default max payload | 1,048,576 bytes (1MB) | `RuntimeConfig.max_payload_size` |
| Hard max payload | 10,485,650 (10 MB) | `MAX_PAYLOAD_SIZE_BYTES` in MFP validation |
| Wire overhead per message | 64 + (2 x frame_depth x 16) | Envelope header + frame open/close |

With the default frame depth of 4, wire overehad is 192 bytes per message. This overhead is MFP's concern — Tessera's payload budget is the full `max_payload_size`.

**Tessera Size budget**

The PIECEE message is the only variable-length message that approacees the payload limit. Its on-wire size is:

piece_wire_size = 5 + tessera_data_length

The default tessera size of 256 KB (262,144 bytes) produces a PIECE payload of 262,149 bytes — comfortably within the 1 MB default. The relationship:

| **Tessera Size** | **PIECE payload** | **Fits in 1 MB default** | **Fits in 10 MB hard limit** |
| --- | --- | --- | --- |
| 64 KB | 65,541 bytes | Yes | Yes |
| 256 KB (Default) | 262,149 bytes | yes | yes |
| 512 KB | 524,292 bytes | yes | yes |
| 1 MB | 1,048,581 bytes | No | Yes |
| 1 MB - 8 bytes | 1,048,568 bytes | Yes | Yes |

**Constraint:** `tessera_size` must satisfy `tessera_size + 5 < max_payload_size`. At the default `max_payload_size` of 1 MB, the maximum tessera size is 1,048,571 bytes. Implementations should validate this at configuration time and reject configurations where the tessera size exceeds the MFP payload budget.

**Control message sizes**

All non-PIECE messages are small and fixed-size:

| Message | Size | Notes |
| --- | --- | --- |
| HANDSHAKE | 43 bytes | Largest fixed-size message |
| BITFIELD | 1 + [N/8] bytes | for N-16,384 (4 GB file): 2,049 bytes |
| REQUEST | 5 bytes | |
| HAVE | 5 bytes | |
| CANCEL | 5 bytes | |
| REJECT | 5 bytes | |
| REJECT | 8 bytes | |
| KEEP_ALIVE | 1 byte | Smallest message |

None of these approach the payload limit under any realistic mosaic size. A BITFIELD for a 1 TB file at 256 KB tessera size would be ~ 512 KB — still within the 1 MB default.

**Manifest transfer**

The manifest is not a Tessera wire message — it is exchanged as part of the swarm join process defined in ts-spec-007 (Swarm & Peer Discovery). However, the manifest must also fit within the MFP's payload limit when transmitted over a channel. For extremely large mosaics, manifest size scales with tessera count (32 bytes per hash tree leaf). A 1 TB file at 256 KB tessera size has ~4 million tessera, producing a hash tree of ~128MB — far exceeding any single MFP message. The manifest transfer strategy (chonked manifest, out-of-band fetch, or pre-shared) is specified in ts-spec-006.

---

## Extensibility

The wire protocol is designed to accomodate new message types and protocol evolution without breaking existing peers.

**Extension message range**

Type values `0x80-0xFF` (128 values) are reserved for extension messages. These are messages defined outside the core Tessera protocol — by plugings, experimental features, or future optional capabilities (e.g., AI-driven metadata exchange via the Intelligence Bridge).

Extension messages follow the same encoding rules as core messages: 1-bytes `msg_type` at offset 0, followed by a type-specific body. The only difference is how unrecognized types are handled.

**Unknown type handling**

A peer that receives a message with an unrecognized `msg_type` must respond to the type range:

| **Range** | **Behavior** |
| --- | --- |
| `0x00` | Reserved. REJECT with `UNKNOWN_MSG_TYPE` |
| `0x01-0x08` | Core types. Must be implemented by all peers |
| `0x09-0x7f` | Reserved for future core types. REJECT with `UNKNOWN_MSG_TYPE` |
| `0x80-0xFF` | Extension types. Silently ignore if not recognized. Do not send REJECT — the sender knows the extension is optional |

This split ensures that core protocol messages are always understood (a peer that cannot parse a core type is broken), while extension messages degrade gracefully (a peer without a particular extension simply ignores those messages).

**Protocol Version Negotiation**

The HANDSHAKE message carries a `version` field (Currently at `0x0001`). Version semantics:

- **Minor changes** (new extension messages, new optional fields appended to existing messages) do not increment the version. Forward-compatible peers silently ignore Unknown trailing bytes.
- **Breaking changes** (altered field layouts, removed message types, changed state machine rules) increment the version. A peer that receives a HANDSHAKE with an unsupported version sends REJECT With `VERSION_MISMATCH` and closes the channel.

A peer must support exactly one protocol version. There is no multi-version negotation — the protocol is young enought that maintaining backward compatibility across breaking changes is not worth the complexity. If a breaking changes is needed, all peers upgrade.

**Adding a new core message type**

To add a new core message type (in the `0x09-0x7F` range):

1. Assign the next sequential `msg_type` value
2. Define the field layout in this spec
3. Define state machine rules — when in the session lifecycle this message may be sent
4. Add error codes if the new message introduce new failure modes
5. Increment the protocol version if the change is not backward-compatible

**Adding an extension message type**

To add an extension message type (in the `0x80-0xFF` range):

1. Choose any unused value in `0x80-0xFF`. No central registry is required — collision is managed by the deployer.
2. Define the field layout in the extension's own documentation, following the encoding conventions
3. Extension messages may only be sent during the transfer phase
4. The sender must tolerate the message being silently ignored by peers that do not implement the extension.

---

# Content Addressing

## Purpose & Scope

This document specifies how Tessera transforms a file into a content-addressed mosaic — the process of chunking, hashing, and manifesting that makes decentralized transfer possible. It is the bridge between the raw file on disk and the wire protocol messages that move tesserae between peers.

**What content addressing provides**

Content addressing means that every artifact in Tessera — every tessera, every manifest — is identified by its cryptographic hash, not by a name, path, or locaiton. This yields three properties:

**Property: Property**
**Mechanism:** a tessera's hash proves its contents are correct. No trust in the sender is required — only trust in the manifest, which is itself hash-verified.

**Property: Deduplication**
**Mechanism:** Identical content produces identical hashes. Two publishers sharing the same file produce the same manifest hash, and peers can serve tesserae interchangeably.

**Property: Immutability**
**Mechanism:** A manifest hash is a permanent identifier. The manifest cannot be altered without changing its hash, which makes it a different mosaic entirely.

**What this spec defines**

- **Chunking.** How the chunker splits a file into fixed-size tesserae, including handling of the final partial tessera and the `ChunkingStrategy` extension point.
- **Hash tree construction.** How SHA-256 leaf hashes are computed from tessera data and combined into a Merke Tree with a single root hash.
- **Manifest format.** The complete field layout of the manifest document — metadata, hash tree, and tessera table.
- **Manifest hashing.** How the manifest hash (the mosaic's identity) is computed from the serialized manifest.
- **Manifest transfer.** How manifests are exchanged between peers, including strategies for large manifests that exceed MFP's payload limit.
- **Integrity verification.** The Piece Verifier's per-tessera check and the Assembler's whole-file check, implementating mitigations for T1 (piece poisoning) and T2 (manifest tampering).

**Relationship to prior specs.**

The Chunker, Assembler, and Piece Verifier are Transfer Engine components defined in ts-spec-004. This spec details their internal logic. The HANDSHAKE message carries `tessera_count` and `tessera_size` — values derived from the manifest defined here. The threat model refernces this spec for T1 and T2 mitigations.

---

## Chunking Process

The Chunker reads a file sequentially and splits it into tesserae of a fixed size. This section specifies the default algorithm and the extension point for alternative strategies.

**Default algorithm: fixed size chunking**

Given a file of `file_size` bytes and a configured `tessera_size` (default 262,144 bytes / 256 KB):

tessera_count = [file_size / tessera_size]

Tesserae are numbered from index 0 to `tessera_count - 1`. Each tessera containts:

| **Index** | **Byte range** | **Size** |
| --- | --- | --- |
| 0 | `[0, tessera_size]` | `tessera_size` |
| 1 | `[tessera_size, 2 x tessera_size]` | `tessera_size` |
| ... | ... | ... |
| N-2 | `[(N-2) x tessera_size, (N-1) x tessera_size]` | `tessera_size` |
| N-1 | `[(N-1) x tessera_size], file_size` | `file_size - (N-1) x tessera_size` |

The final tessera (index N-1) may be smaller than `tessera_size`. This is the only tessera whose size may differ. No padding is applied — the final tessera contains exactly the remaining bytes.

**Edge cases**

**Case: Empty files** (0 bytes)
**Behavior:** `tessera_count = 0`. The manifest has en empty hash tree. The mosaic is immediately complete on creation. The manifest hash is still a valid identifier.

**Case: File smaller than tessera size**
**Behavior:** `tessera_count = 1`. A single tessera contains the entire file.

**Case: File exactly divisible**
**Bevahior:** All tesserae are `tessera_size` bytes. No short final tessera.

**Chunking is determinstic**

For the same file content and the same `tessera_size`, the Chunker **must** produce the same sequence of tesserae, the same hashes, and the same manifest. This is what makes content addressing work — two independent publishes chunking the same file produce the same manifest hash, and their tesserae are interchangeable across swarms.

Determinsm requires:
- Sequential reads starting from byte 0.
- No reordering ot tesserae.
- No internal state carried between files.
- SHA-256 as the sole hash function (no implementation-dependent alternatives)

**ChunkingStrategy extension point**

The Chunker accepts an optional `ChunkingStrategy` protocol:

```python
class ChunkingStrategy(Protocol):
  def chunk(self, file_path: Path, tessera_size: int) -> Iterator[bytes]:
    """Yield tessera payloads from the file"""
    ...

  def tessera_count(self, file_path: Path, tessera_size: int) -> int:
    """Return the total number of tesserae without reading the full file."""
    ...
```

The default implementation is `FixedSizeChunking`, which implements the algorithm above. Alternative strategies (e.g., content-defined chunking by Rabin fingerprinting) can be plugged in by providing a different `ChunkingStrategy`. All strategies must satisfy the same determinism required: same input, same output, every time.

**Constraint:** Regardless of strategy, every tessera produced must satisfy `len(tessera) + 5 < max_payload_size` — the PIECE message size constraint from ts-spec-005. The Chunker validates this before producing the manifest.

---

## Hash Tree Construction

The hash tree is a Merkle tree built from tessera hashes. It enables per-tessera integrity verification without requiring the full file, and its root hash anchors the manifest' identity.

**Leaf Computation**

Each leaf in the hash tree is the SHA-256 of a single tessera's raw bytes:

leaf[i] = SHA-256(tessera[i].data)

Leaf hashes are 32 bytes each. For a mosaic with N tesserae, there are N leaves.

**Tree construction**

The tree is built bottom-up by pairing nodes at each level and hashing their concatenation:

parent = SHA-256(left_child || right_child)

Where || denoyes byte concatenation. Construction proceeds as follows:

1. **Level 0 (leaves):** N leaf hashes, one per tessera.
2. **Level 1:** [N/2] nodes. Each node is `SHA-256(leaf[2k] || leaf[2k+1])`. If N is odd, the last leaf is promoted — it becomes a level-1 node without hashing. It is not duplicated or paired with itself.
3. **Level:** [[N/2]/2] nodes. Same pairing rule applied to level-1 nodes.
4. **Repeat** until a single node remains.
5. **Root:** The final remaining node is the Merkle root hash.

**Odd-node promotion (not duplication)**

When a level has an odd number of nodes, the last node is promoted to the next level as-is. It is not duplicated and paired with a copy of itself. Duplication would mean that a corrupted tessera produces a valid hash if an attacker provides the tessera twice — promotion avoids this.

Example with 5 tesserae:

Level 0: L0   L1      L2         L3     L4
Level 1: H(L0||L1)    H(L1||L2)         L4 <- promoted
Level 2: H(H(L0||L1)) || H(L2||L3)  L4 <- promoted again
Level 3: H( H(H...)) => root

**Special Cases**

| **Case** | **Hash Tree** |
| --- | --- |
| **0 tesserae** empty file | No leaves, no root. The manifest's `root_hash` field is set to 32 zero bytes (`0x00 x 32`). |
| **1 tessera** | The single leaf hash is the root. No internal nodes. `root_hash = SHA-256(tessera[0].data)` |
| **2 tessera** | One internal node: `root_hash = SHA-256(leaf[0])` |

**Verification path**

To verify tesera i, a peer needs the sibling hashes along the path from leaf i to the root. This is the standard Merkle proof — a sequence of (hash, direction) pairs that, when combined with the tessera's own hash, reconstruct the root.

The manifest includes the full leaf hash list, so a peer with the manifest can verify any tessera independently. Merke proofs (partial verification without the full leaf list) are a future optimization — not required in v1, where every peet holds the complete manifest.

**Hash Function**

SHA-256 is used exclusively for all content addressing:
- Tessera leaf hashes
- Internal Merkle tree nodes
- Manifest hashing

Tessera uses Python's `hashlib.sha256`, not MFP's cryptographic primitives. This separation is specified in ts-spec-004: Tessera's content hashing is independent of MFP's channel encryption.

---

## Manifest Format

The manifest is a binary document that fully describes a mosaic. It is the single artifact a fetcher needs to join a swarm, verify every tessera, and assemble the complete file.

**Design principles.**

- **Binary, not text.** The manifest is a compact binary format, not JSON or YAML. This keeps hashing determinstic (no whitespace ambiguity, no key ordering issues) and minimizes size for large mosaics.
- **Fixed header, variable body.** The header is fixed-size for fast parsing. The variable-length sections (metadata, leaf hashes) follow the header.
- **Self-contained.** The manifest includes everything needed for verification — no external lookups required beyond the manifest itself.

**Layout**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | magic               "TSRA" (0x54535241) |
| 4 | 2 | formation_version | Manifest |

Where `M = metadata_len` and `N = tessera_count`

Total manifest size: `60 + M + 32N` bytes.

The magic bytes `TSRA` identify the document as a Tessera manifest. Parsers must reject documents that do not start with these four bytes.

The `format_version` field (currently `0x0001`) allows future changes to the manifest layout. A parser must reject manifests with an unrecognized version.

**Metadata section**

The metadata section carries human and agent readable information about the file. It is encoded as a sequence of length-prefixed UTF-8 key-value pairs:

For each entry:
  1 byte    key_len
  key_len   key   UTF-8 string
  2 bytes   val_len     (u16, big-endian)
  val_len   value       UTF-8 string

Entries are written in sorted key order to ensure determinstic serialization. Duplicate keys are not permitted.

**Defined metadata keys**

| Key | Required | Description |
| --- | --- | --- |
| `name` | Yes | The original filename (without path) |
| `mime` | No | MIME type of the file (e.g., `application/pdf`) |
| `created` | No | ISO 8601 timestamp of when the manifest was created |
| `description` | No | Free-text description of the file content |
| `tags` | No | Comma-separated list of tags for discovery |

Additional keys must be added by publishers. Unknown keys are preserved but not interpreted by the protocol. All metadata values are treated as untrusted input — the sanitization requirements from ts-spec-003 apply before any LLM processing.

**Contraint:** `metadata_len < 65,535` bytes (u16 maximum). This bounds metadata size and prevents manifest bloat. In practice, metadata should be kept small — a few hundred bytes.

**Leaf hashes section**

The leaf hashes are stored as a flat array of 32-byte SHA-256 hashes, one per tessera, in index order:

leaf_hashes[0]    = SHA-256(tessera[0].data)    — 32 bytes
leaf_hashes[1]    = SHA-256(tessera[1].data)    — 32 bytes
...
leaf_hashes[N-1]  = SHA-256(tessera[N-1].data)  — 32 bytes

This section is the largest part of the manifest. Its size is exactly `32 x tessera_count` bytes. For reference:

| File size | Tessera Size | Tessera count | Leaf hashes size | Total manifest |
| --- | --- | --- | --- | --- |
| 1 MB | 256 KB | 4 | 128 bytes | ~250 bytes |
| 100 MB | 256 KB | 400 | 12.5 KB | ~14KB |
| 1 GB | 256 KB | 4,096 | 128 KB | ~128 KB |
| 10 GB | 256 KB | 40,960 | 1.25 MB | ~1.25 MB |
| 1 TB | 256 KB | 4,194,304 | 128 MB | ~128 MB |

The root hash in the manifest is computed from these leaf hashes using the Merkle tree construction in section 3 — it is not stored in the leaf tree hashes array.

---

## Manifest Hashing & Identity

The manifest hash is the mosaic's unique, permanent identifer. It is how peers refer to a mosaic in discovery, handshake, and conversation. This section specifies exactly how it is computed.

**Computation**

The manifest hash is the SHA-256 hash of the **complete serialized manifest**, including the header, metadata, and leaf hashes:

manifest_hash = SHA-256(manifest_bytes)

Where `manifest_bytes` is the full binary document from offset 0 through the end of the leaf hashes section — exactly `60 + metadata_len + (32 x tessera_count)` bytes.

There is no canonical re-serialization step. The hash is computed over the byte-for-byte serialized form. Because the manifest format is fully determinstic (fixed field order, sorted metadata keys, no optional padding), two implementations producing a manifest for the same file with the same `tessera_size` must produce the same `manifest_hash`.

**What the manifest hash covers**

Every field in the manifest contributes to the hash:

**Field:** `magic`, `format_version`
**Consequence of tampering:** A modified magic or version produces a different hash — the manifest is unrecognizable or incompatible

**Field:** `root_hash`
**Consequence of tampering:** Changing the root hash changes the manifest hash. A tampered root hash cannot be used to verify tesserae because the fetchet pins the manifest hash, not the root hash.

**Field:** `tessera_count`, `tessera_size`, `file_size`, `last_tessera_size`
**Consequence of tampering:** Altering any structural field changes the manifest hash. An attacker cannot change the mosaic's geometry without producing a different identity

**Field:** `metadata`
**Consequence of tampering:** Modifying the filename, description or any metadata key-value pair changes the manifest hash.

**Field:** `leaf_hashes`
**Consequence of tampering:** Substituting, reordering, or adding a leaf hash changes the manifest hash.

**Immutability guarantee**

Because the manifest hash covers the entire document, any **modification to the manifest produces a new hash,** and therefore a new mosaic. There is no mechanism to update a manifest in-place. A publisher who changes a file must re-chunk, re-hash, and re-publish — producing a new manifest hash that identifies a new, distinct mosaic.

This eliminates the T3 (stale manifest replay) tension: there is no "newer version" of a manifest at the protocol level. Two manifest hashes are either identical (same mosaic) or different (different mosaics).

**Manifest hash as trust anchor**

The manifest hash is the single root of trust for a mosaic. The security model depends on the fetcher obtaining the correct hash from a trusted source. Once a peer has a trusted manifest hash:

1. Any manifest whose SHA-256 does not match is rejected
2. Any tessera whose SHA-256 does not match its leaf hash in the manifest is rejected
3. The root hash in the manifest is verified by recomputing the Merkle tree from the leaf hashes — if it does not match, the manifest is internally inconsistent and rejected.

The chain of trust lows: **manifest hash** -> **manifest** -> **leaf hashes** -> **individual tesserae.**

---

## Manifest Transfer Strategy

The manifest must reach the fetcher before any tessera exchange can begin. For small mosaics, the manifest fits in a single MFP message. For large mosaics, it does not. This section defines how manifests are exchanged across the full size range.

**Size thresholds**

From section 4, manifest size is `60 + M + 32N` bytes. The critical threshold is MFP's `max_payload_size` (default 1 MB):

| **File Size** | **Tessera Count** | **Manifest size** | **Fits in 1MB?** |
| --- | --- | --- | --- |
| < 8 GB | < 32,736 | < 1 MB | Yes |
| 10 GB | 40,960 | ~1.25 MB | No |
| 100 GB | 409,600 | ~12.5 MB | No |
| 1 TB | 4,194,304 | ~128 MB | No |

The vast majority of mosaics at the target scale (tens-to-hundreds of peers) will have manifests well under 1 MB. The large-manifest strategy exists for completeness and forward compatibility.

**Strategy 1: Inline Manifest (default)**

When the serialized manifest fits within `max_payload_size`, it is sent a single MFP message during the swarm join handshake.

**Flow:**

1. Fetcher establishes an MFP channel with a seeder.
2. Fetcher sends HANDSHAKE containing the manifest hash.
3. Seeder replies with HANDSHAKE
4. If the fetcher does not hey have the manifest, the sender sends the full manifest as a raw arbitrary payload in a dedicated message type.

This requires a wire message to carry the manifest. A new message type is not defined for this — instead, the manifest is requested and delivered using a simple convention on the existing channel:

- The fetcher signals it nees the manifest by setting `tessera_count = 0` in its HANDSHAKE. A seeder receiving a HANDSHAKE with `tessera_count = 0` understands the peer needs the manifest before proceeding.
- The seeder responts with a PIECE message using the reserved index (`0xFFFFFFFF` u32 max), with the manifest bytes as the data payload. This avoids adding a new message type while keeping the manifest transfer within the existing wire protocol.
- The fetcher verifies `SHA-256(data) == manifest_hash` from the HANDSHAKE. On mismatch, the manifest is rejected and the channel is closed.
- After receiving and verifying the manifest, the fetcher re-sends HANDSHAKE with the correct `tessera_count` and `tessera_size` from the manifest, then proceed to BITFIELD exchange.

**Strategy 2: Chunked manifest**

When the manifest exceeds `max_payload_size`, it is split into chunks and delivered as multiple PIECE messages using reserved indices.

**Convention:**

- Manifest chunks use reserved indices starting from `0xFFFFFFFF` and counting downward: `0xFFFFFFFF` (chunk 0), `0xFFFFFFFE` (chunk 1) etc.
- Each chunk is at most `max_payload_size - 5` bytes (the PIECE header overhead).
- The number of chunks is `[manifest_size / (max_payload_size - 5)]`
- The fetcher reassembles the chunks in index order (highest reserved index first) and verifies the complete manifest against the manifest hash.
- The seeder includes the chunk count in its HANDSHAKE response by encoding it in the `tessera_size` field when `tessera_count = 0` in the fetcher's HANDSHAKE. This tells the fetcher how many manifest chunks to expect.

**Strategy 3: Out-of-band manifest**

For extremely large mosaics or scenarios where channel bandwidth is precious, the manifest may be obtained outside the Tessera wire protocol entirely — via a URL, a shared filesystem, or a separate file transfer. In this case:

- The fetcher already has the manifest before establishing any channel.
- The fetcher sends a normal HANDSHAKEK with the correct `tessera_count` and `tessera_size`.
- No manifest transfer occurs on the channel
- The fetcher is responsible for verifying `SHA-256(manifest_bytes) == manifest_hash`

Out-of-band manifest distribution is not specified by this protocol — it is the deployer's responsibility. The protocol only requires the fetcher possesses a verified manifest before entering the transfer phase.

**Strategy selection**

| **Condition** | **Strategy** |
| ------------- | ------------ |
| Fetcher has manifest | No transfer needed. Normal HANDSHAKE |
| Fetcher lacks manifest, manifest < `max_payload_size` | Inline |
| Fetcher lacks manifest, manifest > `max_payload_size` | Chunked |
| Deployed prefers external distribution | Out-of-band |

---

## Integrity Verification

Integrity verification is the enforcement layer of content addressing. It ensures that every byte of the assembled mosaic matches what the publisher originally chunked. Verification happens at three levels, each catching a different class of corruption.

**Level 1: Manifest verification**

Performed once, when the fetcher first receives the manifest.

**Steps:**

1. Compute `SHA-256(manifest_bytes)` over the raw received bytes.
2. Compare against the trusted `manifest_hash` (obtained via HANDSHAKE or out-of-band)
3. If mistmatch: reject the manifest, close the channel, try another peer.
4. If match: parse the manifest header and validate structural consistency:
  - `magic` == `TSRA`
  - `format_version` is supported
  - `tessera_count` == number of leaf hashes present
  - `file_size` is consistent with `tessera_count`, `tessera_size` and `last_tessera_size`:
    - If `tessera_count == 0`: `file_size` must be 0
    - if `tessera_count> 1`: `file_size == last_tessera_size`
    - if `tessera_count > 1`: `file_size == (tessera_count - 1) x tessera_size + last_tessera_size`


---

# Swarm & Peer Discovery

## Purpose & Scope

This document specifies how Tessera peers form, manage, and dissolve swarms — and how they find each other in the first place. It covers the Swarm Manager's four subcomponents (Swarm Registry, Peer Connector, Discovery Client, Capacity Enforcer) defined in ts-spec-004, detailing their internal logic and interactions.

**what this spec defines**

- **Swarm Lifecycle.** The state a swarm passes through from creation (publisher announces) to teardown (last peer leaves), including draining behavior during graceful shutdown.
- **Peer admission and eviction.** How a peer joins a swarm (channel establishment, handshake, manifest exchange, bitfield swap), and when a peer is disconnected (scoring thresholds, protocol violations, capacity limits).
- **Discovery backend protocol.** The `DiscoveryBackend` interface that all discovery implementations must satsifty — `announe()`, `lookup()`, `unannounce()` — and the contract each method must honor.
- **Default discovery backend.** The centralized tracker client that ships as the default implementation, including its announce/lookup wire interaction.
- **Multi-source verification.** How the Discovery Client cross-reference results whem multiple backends are active, implementing the T8 (discovery poisoning) mitigation.
- **Capacity enforcement.** How the Capacity Enforcer bounds resource consumption — maximum peers per swarm, maximum swarms per node — and the rejection behavior when limits are reached.
- **Network partition and reconnection.** How the Swarm Manager detects peer unavailability, attemots reconnection, and recovers swarm state after a network partition.

**Relationship to prior specs**

The Swarm Manager communicates laterally with the Transfer Engine: it tells the Transfer Engine which peers are available, and the Transfer Engine tells the Swarm Manager when a peer should be scored down or disconnected. The wire protocol defines the messages exchanged during peer admission — this spec defines when and why those messages are sent. The threat model assigns this spec responsibility for T4(sybil flooding) and T* (discovery poisoning) mitigations.

---

## Swarm Lifecycle

A swarm is the set of peers participating in the transfer of a specific mosaic, identified by its manifest hash. Swarms are ephemeral — they exist as long as at least one peer is interested in the mosaic. The Swarm Registry tracks all active swarms on the local node.

**States.**

A swarm on a given node passes through four states:

**State: PENDING**
**Description:** The swarm entry has been created in the Swarm Registry and the node has announced to the discovery service, but no peer channels have been established yet. For a publisher, this begins when `publish()` completes chunking. For a fetcher, this begins when `fetch()` starts discovery lookup.

**State: ACTIVE**
**Description:** At least one peer channel is established. Tessera exchange is in progress (fetcher) or the node is serving requests (seeder). The swarm remains ACTIVE as long as at least one channel is open and the node has not requested shutdown.

**State: DRAINING**
**Description:** The node has initiated graceful shutdown or the user has cancelled the transfer. No new peer conncetions are accepted. Existing in-flight PIECE deliveries are allowed to complete. REJECT with `SHUTTING_DOWN` is sent in response to new REQUESTS.

**State: CLOSED**
**Description:** All channels are closed, all in-flight operations have completed. The swarm entry is removed from the Swarm Registry. The node unannounces from the discovery service.

**Swarm creation**

**Publisher Path:**

1. Chunker produces the manifest.
2. Swarm Registry creates a new entry: `manifest_hash -> {state: PENDING, role: SEEDER, peers:[]}`
3. Discovery Client calls `announce(manifest_hash, agent_id)` on all active backends.
4. MFP agent is bound if not already bound (one agent per Tessera node, shared across swarms)

**Fetcher path:**

1. Application Interface receives `fetch(manifet_hash)`
2. Swarm Registry creates a new entry: `manifest_hash -> {state: PENDING, role: LEECHER, peers: []}`
3. Discovery Client calls `lookup(manifest_hash)` on all active backends.
4. Peer Connector begins establishing channels with discovered peers.
5. Swarm transitions to ACTIVE when the first channel completes the HANDSHAKE + BITFIELD exchange

**Role transition**

A leecher that completes the mosaic (all tesserae received and whole-file verified) transitions to seeder:

1. The Swarm Registry updates the role from `LEECHER` to `SEEDER`
2. The node continues serving tesserae to other peers in the swarm
3. Discovery Client re-announces with the upload role if the backend supports role differentiation.

The transition is local — no wire message is sent. Connected peers already know this node's bitfield (all-ones after completion).

**Swarm teardown**

A swarm is torn down when:

- **Fetcher completes and does not want to seed.** The user or agent calls `cancel()` or the node's seeding policy decides not to seed. The swarm transitions to DRAINING / CLOSED.
- **Publisher stops seeding.** The swarm transitions to DRAINING / CLOSED
- **All peers disconnect.** The swarm remains in ACTIVE with zero peers. If no new peer connects within a confiugrable idle timeout, the swarm transitions to CLOSED
- **Node shutdown.** All swarms transition to DRAINING simultaneously. The shutdown timeout bounds total draining time.

## Peer Admission & Eviction

The Peer Connector manages the lifecycle of individual peer connections within a swarm. Every connection passes through admission (channel establishment and handshake) and may end in eviction (voluntary or forced disconnection).

**Admission Sequence**

When a fetcher discovers a peer or a seeder receives an incoming channel request, the Peer Connector executes the following sequence:

Peer Connector                                Remote Peer
      |   1. Check Capacity Enforcer                |
      |       (reject if swarm/node full)           |
      |   2. establish_channel(peer_agent_id)       |
      |—————— MFP channel boostrap ————————————————>|
      |                                             |
      |   3. HANDSHAKE exchange                     |
      |———— ts-spec-005 state machine —————————————>|
      |                                             |
      |   4. Manifest exchange (if needed)          |
      |       ts-spec-006, section 6                |
      |                                             |
      |   5. BITFIELD exchange                      |
      |—————ts-soec-005 state machine —————————————>|
      |<————————————————————————————————————————————|
      |                                             |
      |   6. Register peer in Swarm Registry        |
      |   7. Notify Transfer Engine                 |

**Step details**

1. **Capacity check.** Before allocating any resources, the Capacity Enforcer verifies that the Swarm has not reached `max_peers_per_swarm` and the node has not reached `max_swarms_per_node`. If either limit is hit, the connection is rejected — for incoming connections, a REJECT with `SWARM_FULL` is sent after HANDSHAKE.
2. **Channel establishment.** The Peer Connector calls `handle.establish_channel(peer_agent_id)` to create an MFP bilateral channel. This performs the X25519 key exchange and establishes the encrypted pipe. If the channel cannot be established (peer unreachable, key exchange failure), the admission fails silently — the Peer Connector moves on to the next discovered peer.
3. **Handshake.** Both peers exchange HANDSHAKE messages. The Peer Connector verifies:
  - `manifest_hash` matches the local swarm's manifest hash. Mismatch -> REJECT with `MANIFEST_MISMATCH`, close channel.
  - `version` is supported. Mismatch -> REJECT with `VERSION_MISMATCH`, close channel.
4. **Manifest exchange.** If the fetches does not yet have the manifest (signaled by `tessera_count = 0` in its HANDSHAKE), the seeder delivers it via the inline or chunked strategy defined ts-spec-006. The fetcher verifies the manifest against the trusted manifest hash before proceeding
5. **Bitfield exchange.** Both peers send their BITFIELD. The Peer Connector passes the remote peer's bitfield to the BITFIELD Manager in the Transfer Engine.
6. **Registration.** The peer is added to the swarm's peer list in the Swarm Registry with initial metadata: `{agent_id, channel_id, role, bitfield, connected_at, score: 0.0}`.
7. **Notification.** The Transfer Engine is notified that a new peer is available. The Request Scheduler may immediately begin issuing REQUESTs if the peer holds needed tesserae.


**Eviction Triggers**

A peer is evicted (channel closed, removed from Swarm Registry) when any of the following occur:

| **Trigger** | **Source** | **Behavior** |
| --- | --- | --- |
| **Peer score below threshold** | Peer Scorer | The peer's cumulative score (latency, failure rate, hash mismatches) falls below `min_peer_score`. The Swarm Manager closes the channel |
| **Protocol Violation** | Wire protocol state machine | Receiving an invalid message (UNEXPECTED_MSG, DUPLICATE_MSG, MALFORMED_MSG) that suggests an incompatible or malicious peer. Channel closed immediately. |
| **Repeated hash mismatches** | Piece verifier | A peer that serves `max_hash_failures` poisoned tesserae within a sliding window is evicted and its AgentId is added to a per-swarm blocklist for the duration of the swarm. |
| **Channel closed by remote** | MFP channel status | The remote peet closed the channel or the MFP runtime reports the channel as CLOSED. The peer is removed from the registry. |
| **MFP quarantine** | MFP quarantine | The peer's agent has been quarantined by MFP (rate limiting, validation failure). The channel becomes unusable. The peer is removed. |
| **Capacity Rebalancing** | Capacity Enforcer | When a higher-scoring peer requests admission and the swarm is full, the lowest-scoring peer may be evicted to make room (only if its score is below `eviction_threshold`) |

**Per-swarm blocklist**

When a peer is evicted for hash mistmatches or repeated protocol violations, its AgentId is added to the swarm's blocklist. Blocklisted peers are rejected at step 1 of admission — before channel establishment — for the lifetime of the swarm. The blocklist is not persisted across swarm restarts and does not apply to other swarms.

---

## Discovery Backend Protocol

The Discovery Backend does not implement discovery logic directly. It delegates to one or more `DiscoveryBackend` implementations — pluggable components that know how to find peers for a given manifest hash. This section defines the interface that all backends must satisfy.

**Interface**

```python
class DiscoveryBackend(Protocol):
  async def announce(
    self,
    manifest_hash: bytes,
    agent_id: bytes,
    role: Literal["seeder", "leecher"],
  ) -> None:
    """
    Register this peer as participating in the swarm for the given manifest.
    Called when a swarm is created (publish or fetch) and when a leecher transitions to seeder. Backends that do not support role differentiation may ignore the role parameter.
    Must be idempotent — calling announce twice with the same arguments has no additional effect.
    """
    ...

  async def lookup(
    self,
    manifest_hash: bytes,
  ) -> list[PeerRecord]:
    """
    Return a list of peers known to hold (or be fetching) the given manifest.
    Returns an empty list if no peers are found. Must not raise on "not found" — absence is a valid result.
    Results may be stale. The caller (Discovery Client) is responsible for verifying that returned peers are reachable and hold the correct manifest.
    """
    ...

  async def unannounce(
    self,
    manifest_hash: bytes,
    agent_id: bytes
  ) -> None:
    """
    Remove this peer from the swarm listing for the given manifest.
    Called when a swarm transitions to CLOSED. Must be idempotent — unannouncing a peer that is not listed is a no-op.
    """
    ...
```

**PeerRecord**

```python
@dataclass
class PeerRecord:
    agent_id: bytes         # 32-byte MFP AgentId
    role: str               # "seeder" or "leecher"
    last_seen: float        # Unix timestamp of last announce/refresh
    source: str             # Name of the backend that returned this record
```

The `source` field is set by the Discovery Client, not the backend itself. It identifies which backend produced the record — used for multi-source verification.

**Contract**

All `DiscoveryBackend` implementations must honor the following:

| **Rule** | **Rationale** |
| -------- | ------------- |
| All methods are asnyc | Discovery may involve network I/O (tracker queries, gossip rounds). The Swarm Manager runs on asyncio |
| `announce` and `unannounce` are idempotent | The Swarm Manager may retry on transient failure without side effects. |
| `lookup` never raise for "not found. | An empty list is the correct response. Exceptions are reserved for backend failures (network error, malformed response). |
| `lookup` results are best-effort | Results may be stale, imcomplete, or contain peers that are no longer reachable. The Peer Connector validates every returned peer during admission. |
| Bakcneds must tolerate concurrent calls. | Multiple swarms may call `announce`, `lookup`, and `unannounce` concurrently from different asyncio tasks. |
| Backends must not block the event loop. | If the backend performs blocking I/O (e.g., a synchronous HTTP client), it must use `asyncio.to_thread()`. |

**Backend Registration**

The Discovery Client is configured with a list of backends at node startup via `TesseraConfig`. Backends are ordered — the first backend is the primary, subsequent backends are secondary. The order affcts multi-source verification but not `announce/unannounce`, which are called on all backends.

```python
config = TesseraConfig(
  discovery_backends=[
    TrackerBackend(url="https://tracker.example.com"),
    GossipBackend(seed_peers=[...]),
  ]
)
```

---

## Default Discovery Backend

Tessera ships with a single built-in discovery backend: a centralized tracker client. It is the simplest backend that satisfies the `DiscoveryBackend` protocol and is sufficient for the target scale of tens-to-hundreds of peers.

**Architecture**

The tracket is a lightweight HTTP service that maps manifest hashes to peer lists. It is **not** part of the Tessera node — it runs as a separate process or service. The `TrackerBackend` is the client-side component that communicates with the tracker over HTTPS.

```
Tessera Node A            Tracker service           Tessera Node B
      |                           |                         |
      |—— POST / announce ———————>|                         |
      | {manifest_hash, agent_id, |                         |
      |  role:"seeder"}           |                         |
      |                           |                         |
```

The tracker is a directory, not a relay. It never sees tessera data, manifests, or MFP messages. Its only job is to answer "which agentId are in the swarm for this manifest hash?"

**TrackerBackend implementation**

```python
class TrackerBackend:
    def __init__(self, url: str, refresh_interval: float=60.0):
      self.url = url
      self.refresh_interval = refresh_interval

    async def announce(self, manifest_hash, agent_id, role):
      # POST /announce
      # Body: {manifest_hash (hex), agent_id (hex), role}
      # Response: 200 OK or 409 Already Announced (idempotent)

    async def lookup(self, manifest_hash):
      # GET /lookup?hash={manifest_hash_hex}
      # Response: 200 with JSON array or PeerRecord-like objects
      # Response: 200 with empty array if no peers found

    async def unannounce(self, manifest_hash, agent_id):
      # POST /unannounce
      # Body: {manifest_hash (hex), agent_id(hex)}
      # Response: 200 OK or 404 Not Found (idempotent)
```

**Tracker API surface**

| Endpoint | Method | Request | Response |
| -------- | ------ | ------- | -------- |
| `/announce` | POST | `{manifest_hash, agent_id, role}` | `200 OK` |
| `/lookup` | GET | `?hash={manifest_hash_max}` | `200` with `[{agent_id, role, last_seen}]` |
| `/unannounce` | POST | `{manifest_hash, agent_id}` | `200 OK` |
| `/health` | GET | — | `200 OK` |

All requests and response bodies are JSON. Manifest hashes and AgentIds are hex-encoded strings.

**Tracker responsibilities**

| The tracker does | The tracker does not |
| ---------------- | -------------------- |
| Store manifest_hash -> peer list mappings | Store or relay manifests, tesserae, or MFP messages |
| Expire stale announcements (peers that have not refreshed within TTL) | Authenticated peers — any peer with a valid AgentId can announce |
| Return peer lists for lookup queries | Verify that peers actually hold the claimed manifest |
| Serve as a single point of coordination | Participate in the swarm or transfer protocol |

**Announce refresh**

The `TrackerBackend` periodically re-announces to prevent stale expiry. Every `refresh_interval` seconds (default 60), it re-sends `announce()` for all active swarms. The tracker treats each announce as a heartbeat — updating the `last_seen` timestamp. Peers that have not refreshed within the tracker's configured TTL (tracker-side setting, not specified by Tessera) are pruned from lookup results.

**Tracker as a single point of failure**

The centralized tracker is a single point of failure for discovery — not for transfer. If the tracker is down:

- **Existing swarms continue.** Peers already connected via MFP channels are unaffected. Tessera exchange continues normally.
- **New fetchers cannot discover peers.** `lookup()` fails, and the fetcher cannot find seeders. The fetcher retries with exponential backoff.
- **New publishers cannot announce.** `announce()` fials, but the publisher holds the manifest and tesserae locally. It can re-annoounce when the tracker recovers.

For deployments that require higher discovery availability, operators should configure multiple backends or implement a gossip-based backend.

## Multi-Source Verification

Whrn multiple discovery backends are configured, the Discovery Client cross-references their results to reduce the risk of discovery poisoning. A single compromised backend cannot unlaterally direct a fetcher into a hostile swarm.

**Lookup Aggregation**

When `lookup(manifest_hash)` is called, the Discovery Client queries all configured backends concurrently and merges the result:

```
Discovery Client
    |
    |— lookup() -> backend A -> [peer 1, peer 2, peer 3]
    |— lookup() -> backend B -> [peer 1, peer 3, peer 4]
    |— lookup() -> backend C -> [peer 2, peer 3, peer 5]
      Merged: peer1(A,B) peer2(A,C) peer3(A,B,C) peer4(B) peer5(C)
```

Each peer in the merged result carries the set of backends that returned it (the `source` field in `PeerRecord`)

**Trust scoring**

Peers are ranked by the number of backends that independently corroborate their presence:

| **Corroboration** | **Trust level** | **Behavior** |
| ----------------- | --------------- | ------------ |
| Returned by all backends | **High** | Conencted first. No additional verification needed beyond the standard HANDSHAKE |
| Returned by majority of backends | **Medium** | Connected after high-trust peers. Standard admission sequence. |
| Returned by a single backend | **Low** | Connected last. Subject to stricter initial scrutiny — the Peer Connector applies a shorted HANDSHAKE timeout and the Peer Scorer starts the peet at a lower initial score. |

**Connection ordering**

The Peer Connector processes discovered peers in trust-score order:

1. **High-trust peers** — connected first, up to `max_peers_per_swarm`
2. **Medium-trust peers** — conneccted if capacity remains
3. **Low-trust peers** — connetected only if insufficient high/medium-trust peers are available

Within the same trust level, peers are ordered by role (seeders before leechers) and then by `last_seen` (most recently seen first).

**Single-backend mode**

When only one backend is configured (the common case with the default `TrackerBackend`), multi-source verification is not possible. All peers are treated as medium-trust. The T8 mitigation is this mode relies entirely on the HANDSHAKE manifest hash check — a peer returned by a compromised tracker that does not hold the correct manifest is rejected at admission step 3.

**Backend failure handling**

| **Scenario** | **Behavior** |
| ------------ | ------------ |
| One backend fails, others succeed | Proceed with results from successful backends. Log the failure. Failed backend's results are treated as "empty" — peers only returned by the failed bakcned are not penalized |
| All backends fail | `lookup()` returns an empty list. The fetcher retries with exponential backoff |
| One backend is slow | The Discovery Client imposes a per-backend timeout (configurable, default 10 seconds). Results from backends that respond within the timeout are merged; slow backends are treated as failed for that lookup round. |

**Announce and unannounce**

Unlike `lookup`, `announce`, and `unannounce` are not cross-referenced — they are broadcast to all backends unconditionally. If one backend fails to receive an announce, the peer is still discoverable via the others. If one backend fails to receive an unannounce, it will eventually expire the stale entry via its TTL.

---

## Capacity Enforcement

The Capacity Enforcer prevents resource exhaustion by bounding the number of peers per swarm and the number of active swarms per node. Without these limits, a sybil attacker or a burst of legitimate fetchers oculd consume all available channels, memory, and bandwidth.

**Limits**

| **Limit** | **Scope** | **Default** | **Configurable via** |
| --------- | --------- | ----------- | -------------------- |
| `max_peers_per_swarm` | Per swarm | 50 | `TesseraConfig` |
| `max_swarms_per_node` | Per node | 10 | `TesseraConfig` |
| `max_channels_per_agent` | Per MFP agent | Inherited from MFP `RuntimeConfig` | MFP configuration |

This effective per-node channel limit is `min(max_peers_per_swarm x active_swarms, max_channels_per_agent)`. If MFP's channel limit is lower than Tessera's, MFP's limit govers — channel establishment will fail at the MFP layer before Tessera's limits are reached.

**Enforcement Points**

| **Event** | **Check** | **Rejection** |
| --------- | --------- | ------------- |
| **Incoming channel request** | `swarm.peer_count` < max_peers_per_swarm | `REJECT with SWARM_FULL` after HANDSHAKE. Channel closed |
| **Outgoing `connection` attempt** | `swarm.peer_count < max_peer_per_swarm` | `Connection not attempted`. Peer skipped, tried later if capacity frees. |
| **New swarm creation (`publish or fetch`)** | `node.swarm_count < max_swarms_per_node` | `publish()` or `fetch()` `raises an error`. The caller must wait for an existing swarm to close |

**Capacity rebalancing**

When a swarm is full and a new peer requests admission, the Capacity Enforcer may evict the lowest-scoring existing peer to make room — but only if:

1. The new peer's discovery trust level is higher than the existing peer's current score, and
2. The existing peer's score is below `eviction_threshold` (a configurable value, default 0.2 on a 0.0-1.0 scale).

This prevents a well-behaved peer from being displaced by every new arrival while still allowing the swarm to improve its peer quality over time. If neither condition is met, the new peer receives REJECT with `SWARM_FULL`.

**Interaction with MFP limits**

MFP imposes its own resource limits:

| **MFP Limit** | **Effect on Tessera** |
| ------------- | --------------------- |
| `max_agents` | Tessera uses one agent per node. This limit is not relevant unless the node runs other MFP applications concurrently. |
| `max_channels_per_agent` | Hard cap on total peer connections across all swarms. If reached, `etablish_channel()` fails and the Peer Connector treats it as a capacity rejection. |
| `max_message_rate` | Peers that exceed MFP's rate limit are quarantined automatically. Tessera detects this via channel status and evicts the quarantined peer. |

**Monitoring**

The Capacity Enforcer exposes the following to the Application Interface:

- Per-swarm: current peer count, capacity remaining, number of rejected admission
- Per-node: active swarm count, total channel count, capacity remaining

These values are available through `status()` for human operators and agent callers.

---

## Network Partition & reconnection

Network fails. Peers disappear without sending SHUTTING_DOWN. Channels drop silently. This section specifies how the Swarm Manager detects, responds to, and recovers from peer unavailability and network partitions.

**Detection**

Peer unavailability is detected through three mechanisms:

**Mechanism: MFP Channel Closure**
**Detection Time:** Immediate
**Source:** MFP runtime reports channel status as CLOSED. Triggered by TCP connection drop, remote process crash, or explicit close.

**Mechanism: KEEP_ALIVE timeout**
**Detection time:** `2 x keep_alive_interval` (default 60s)
**Source:** If no message of any type (including KEEP_ALIVE) is received from a peet within the timeout window, the peer is presumed dead.

**Mechanism: Request timeout**
**Detection time:** Configurable per-request (default 30s)
**Source:** A REQUEST that receives no PIECE or REJECT within the timeout contributes to the peer's failure rate. After `max_consecutive_timeouts` (default 3), the peer is presumed unavailable.

The three mechanisms cover different failure modes: hard disconnects (MFP closure), silent disappearance (KEEP_ALIVE), and degraded responsiveness (request timeout).

**Response**

When a peer is detected as unavailable:

1. **Remove from Swarm Registry.** The peer's entry is deleted. Its channel is closed if not already.
2. **Reclaim in-flight requests.** Any REQUESTs sent to the unavailable peer that have not been answered are returned to the Request Scheduler's pending queue. The scheduler re-issues them to other available peers.
3. **Update bitfield availability.** The bitfield manager recalculates tessera availability across remaining peers. If tesserae that were only available from the lost peer are no unavailable from any connected peer, the Discovery Client is triggered to find new peers.
4. **Update peer scores.** The Peer Scorer records the disconnection. Peers that disconnect cleanly (SHUTTING_DOWN received) are not penalized. Peers that disappear silently receive a score penalty.
5. **Re-discover if needed.** If the swarm's peer count falls below `min_peers_threshold` (default 2) or if needed tesserae are no longer available from any connected peer, the Discovery Client re-runs `lookup()` to find additional peers.

**Reconnection strategy**

The Swarm Manager does not attempt to reconnect to a specific peer that has disconnected. Instead, it relies on discovery to find peers — which may include the previously disconnected peer if it has recovered and re-announced.

Rationale: MFP channels are stateful (ratchet position, key material). A dropped channel cannot be resumed — a new channel must be established from scratch. Since the new channel requires a full admission sequence (HANDSHAKE, manifeest exchange, BITFIELD), there is no advantage to targeting a specific peer over discovering any available peer.

**Partition Recovery**

A network partition splits the swarm into isolated subgroups. From each subgroup's perspective, the peers in other subgroups have simply become unavailable. The response is the same as individual peer loss:

1. Unavailable peers are removed from the Swarm Registry
2. In-flight requests are reclaimed
3. Discovery is re-triggered if the remaining peer count is insufficient

When the partition heals:

- Peers that re-announce the discoveray service become discoverable again
- New channels are established through the normal admission sequence
- Bitfields are exchanged afresh — no assumption is made about what the peer held before the partition
- Transfer resumes from where each peer left off. The Request Scheduler sees new peers with new bitfields and incorporates them into its selection strategy.

**Swarm Starvation**

If all peers become unavailable and discovery returns no new peers, the swarm enters starvation:

1. The swarm remains in ACTIVE state with zero peers
2. The Discovery Client retries `lookup()` with exponential backoff: 5s, 10s, 20s, 40s, up to a maximum interval of 5 minutes.
3. If no peers are found within `starvation_timeout` (configurable, default 30 minutes), the swarm transitions to CLOSED and `fetch()` returns an

---

# API & CLI Design

## Purpose & Scope

This document defines Tessera's public surface — the API that python callers use to publish, fetch, and manage mosaics, the CLI that wraps it for terminal use, and the configuration object that ties together every configurable value references across specs 04-09.

**What this spec defines**

- **Public API.** The five Python functions — `publish()`, `fetch()`, `query()`, `status()`, `cancel()` — their signatures, parameters, return types, and async semantics. This is the library entry point.
- **CLI commands.** The command line interface that maps terminal commands to API calls. Designed for human operators and shell scripts.
- **TesseraConfig.**  The single configuration daataclass that every other component reads. Centralizes all configurable defaults that prior specs referenced via "configurable via ts-spec-010".
- **Error handling.** The exception hierarchy and error semantics. How API callers distinguish between recoverable and fatal errors.
- **Event callbacks.** The `on_manifest_created`, `on_manifest_received`, and progress callback hooks from ts-spec-004.

**Design principles**

- **Library first.** The API is the primary interface. The CLI is a thin wrapper around it. No functionality exists only in the CLI.
- **Agent-native.** Every API function is `async`, returns structured data (dataclasses, not formatted strings), and is designed to be called by autonomous agents as naturally as by humans.
- **20-line cycle.** A complete publish-discover-fetch cycle should be expressible in under 20 lines of application code.
- **Fail explicit.** Errors are typed exceptions, not return codes or sentinel values. The caller always knows what went wrong and whether it can retry.

---

## Public API

The public API consists of five async functions and one constructor. All importable from `Tessera`:

```python
from tessera import TesseraNode, TesseraConfig
```

**TesseraNode**

The entry point. A `TesseraNode` encapsulates a running Tessera instance — one MFP agent, one Swarm Manager, one Transfer Engine.

```python
class TesseraNode:
  def __init__(self, config: TesseraConfig | None = None):
    """
    Create a tessera node.

    Args:
      config: Configuration. If None, all defaults are used.
    """

  async def start(self) -> None:
    """
    Bind the MFP agent and start background tasks.
    Must be called before any other method.
    """

  async def stop(self) -> None:
    """
    Graceful shutdown. Transitions all swarms to DRAINING, waits for in-flight operations, unbinds the MFP agent.
    """

  async def __aenter__(self) -> "TesseraNode": ...
  async def __aexit__(self, *exc) -> None: ///
```

`TesseraNode` supports `async with` for automatic start/stop:

```python
async with TesseraNode(config) as node:
  manifest_hash = await node.publish("report.pdf")
```

**`publish()`**

```python
async def publish(
  self,
  file_path: str | Path,
  metadata: dict[str, str] | None = None,
  skip_moderation: bool = False,
) -> bytes:
  """
  Chunk a file, build the manifest, announce the discovery, and begin seeding.

  Args:
    file_path: Path to the file to publish.
    metadata: Optional metadata key-value pairs. 'name' is auto-populated from the
    filename if not provided.
    skip_moderation: If True, bypass the content moderation gate.

  Returns:
    The manifest hash (32 bytes). This is the mosaic's identity.

  Raises:
    FileNotFoundError: file_path does not exist.
    ModerationError: Content moderation rejected the file (and skip_moderation is False).
    CapacityError: max_swarms_per_node reached.
    TesseraError: chunking or manifest creation failed.
```

**`fetch()`**

```python
async def fetch(
  self,
  manifest_hash: bytes,
  output_path: str | Path | None = None,
  skip_moderation: bool = False,
  on_progress: Callable[[TransferStatus], None] | None = None,
) -> Path:
  """
  Join the swarm for a mosaic, download all tesserae, and assemble the file.

  Args:
    manifest_hash: The 32-byte manifest hash identifying the mosaic.
    output_path: Where to write the assembled file. If None, uses the filenamfe from the manifest metadata in the current directory.
    skip_moderation: If True, bypass the content moderation gate.
    on_progress: Optional callback invoked after each tessera is verified. Receives
    a TransferStatus snapshot.

  Returns:
    Path to the assembled file on disk.

  Raises:
    ModerationError: Content moderation rejected the manifest metadata.
    CapacityError: max_swarms_per_node reached.
    StarvationError: No peers found within stravation_timeout.
    IntegrityError: whole-file verification failed after max retries.
    TesseraError: Transfer failed for another reason.
```

**`query()`**

```python
async def query(
  self,
  text: str,
  max_results: int = 10,
) -> list[DiscoveryResult]:
  """
  Search for mosaics by natural-language description.
  Requires madakit. Returns an empty list if madakit is not configured or the LLM call fails.

  Args:
    text: Natural-language query.
    max_results: Maximum number of results to return.

  Returns:
    List of DiscoveryResult, sorted by relevance_score descending.
    Empty list if no matches or madakit is unavailable.
```

**`status`**

```python
async def status(
  self,
  manifest_hash: bytes | None = None,
) -> TransferStatus | list[TransferStatus] | NodeStatus:
  """
  Get transfer and node status.

  Args:
    manifest_hash: If provided, return status for that specific mosaic.
                    If None, return status for all active swarms.
  Returns:
    TransferStatus for a specific mosaic, list of TransferStatus for all active swarms, or NodeStatus if no swarms are active.

  Raises:
    KeyError: manifest_hash is not an active swarm.
  """

  @dataclass
  class NodeStatus:
    agent_id: bytes
    active_swarms: int
    total_peers: int
    capacity_remaining: int
    ai: AIStatus | None
```

**`cancel()`**

```python
async def cancel(
  self,
  manifest_hash: bytes,
) -> None:
  """
  Cancel an active transfer and leave the swarm.
  Transitions the swarm to DRAINING. In-flight pieces are allowed to complete. The swarm is fully closed when draining finishes.

  Args:
    manifest_hash: The mosaic to cancel.

  Raises:
    KeyError: manifest_hash is not an active swarm.
```

**`SC5 demonstration`**

A complete publish-discover-fetch cycle in under 20 lines:

```python
import asyncio
from tessera import TesseraNode, TesseraConfig

async def main():
  config = TesseraConfig()

  async with TesseraNode(config) as publisher:
    manifest_hash = await publisher.publish("report.pdf",
      metadata={"description": "Q3 revenue report"})
      print(f"Published: {manifest_hash.hex()}")

  async with tesseraNode(config) as fetcher:
    results = await fetcher.query("Q3 revenue")
    if results:
      path = await fetcher.fetch(results[0].manifest_hash)
      print(f"Fetched: {path}")

asyncio.run(main())
```

## CLI Commands

The CLI is a thin wrapper around the public API. Every command maps to exactly one `TesseraNode` method. No functionality exists only in the CLI:

**Invocation**

```shell
tessera <command> [options]
```

Global options apply to all commands:

| **Option** | **Type** | **Default** | **Description** |
| ---------- | -------- | ----------- | --------------- |
| `--config` | path | None | Path to a TOML config file. Overrides all default |
| `--data-dir` | path | `~/.tessera` | Root storage directory |
| `--bind` | host:port | `0.0.0.0:0` | MFP agent bind address |
| `--tracker` | URL | None | Tracker URL. May be specified multiple times. |
| `--log-level` | str | `info` | Logging verbosity: `debug`, `info`, `warning`, `error` |
| `--json` | flag | False | Emit machine-readable JSON instead of human-friendly text |

**`tessera publish`**

```shell
tessera publish <file> [--meta KEY=VALUE ...] [--skip-moderation]
```

Maps to `TesseraNode.publish()`

| **Argument/Option** | **Maps to** | **Notes** |
| ------------------- | ----------- | --------- |
| `<file>` | `file_path` | Required positional argument. |
| `--meta KEY=VALUE` | `metadata` | Repeatable. Parsed into `dict[str, str]` |
| `--skip-moderation` | `skip_moderation` | Flag. |

**`Output (text):`**
Published:  q3f2...c891
Seeding. Press ctrl-C to stop.

**`Output (--json)`**
```json
{"manifest_hash": "a3f2...c891", "status": "seeding"}
```

The process remains alive and seeds until interrupted. On `SIGINT` / `SIGTERM`, the node drains gracefully before exiting.

**`tessera fetch`**

```shell
tessera fetch <manifest_hash> [--output PATH] [--skip-moderation]
```

Maps to `TesseraNode.fetch()`

## TesseraConfig

The single configuration object read by every component.

```python
@dataclass
class TesseraConfig:
  """
  Complete Tessera configuration.

  All fields have sensible defaults. Pass to TesseraNode() to override.
  """

  # --- Node identity ---
  data_dir: Path = path("~/.tessera")
  """Root directory for all on-disk state."""

  bind_address: str = "0.0.0.0"

  bind_port: int = 0
  """MFP agent bind port. 0 = OS-assigned."""

  # --- Chunking ---
  tessera_size: int = 262_144
  """Default Tessera size in bytes (256 KB). Must be < max_payload_size - 5"""

  # --- Swarm Management ---
  max_peers_per_swarm: int = 50
  """Maximum concurrent peers in a single swarm."""

  max_swarms_per_node: int = 10
  """Maximum concurrent swarms this node participates in."""

  eviction_threshold: float = 0.2
  """Peer score below which a peer is evicted."""

  starvation_timeout: float = 120.0
  """Seconds with zero peers before a fetch raises StarvationError."""

  starvation_backoff_base: float = 5.0
  """Base delay (seconds) for exponential backoff during starvation re-discovery."""

  starvation_backoff_max: float = 60.0
  """Maximum backoff delay (seconds) between re-discovery attempts."""

  # --- Transfer Engine ---
  max_requests_per_peer: int = 5
  """Maximum concurrent piece requests to a single peer."""

  max_requests_per_swarm: int = 20
  """Maximum concurrent piece requests across all peers in swarm."""

  request_timeout: float = 30.0
  """Seconds before a piece request times out."""

  max_retries_per_tessera: int = 10
  """Maximum retry attempts for a single tessera before marking it stuck."""

  endgame_threshold: int = 20
  """Enter endgame mode when remaining pieces < this value and all are requested."""

  max_endgame_requests: int = 100
  """Maximum total duplicate requests during endgame mode."""

  # --- Peer scoring ---
  score_weight_latency: float = 0.3
  """Weight for latency metric in peer scoring."""

  score_weight_failure: float = 0.4
  """Weight for failure-rate metric in peer scoring."""

  score_weight_throughput: float = 0.3
  """Weight for throughput metric in peer scoring."""

  score_penalty_mismatch: float = 0.25
  """Penalty per hash mismatch in peer scoring."""

  score_min: float = 0.1
  """Minimum score; peers below this are evicted."""

  score_deprioritize: float = 0.3
  """Score below which peers are deprioritize in selection."""

  # --- Discovery ---
  discovery_backends: list[str] = field(defalt_factory=lambda: ["tracker"])
  """Active discovery backend names. Each must have a corresponding backend registered."""

  tracker_urls: list[str] = field(default_factory=list)
  """Tracker endpoint URLs for the default TrackerBackend."""

  tracker_announce_interval: float = 1800.0
  """Seconds between tracker re-announce."""

  # --- AI integration ---
  ai_enabled: bool = True
  """Enable madakit integration. If True but madakit is not installed, degrades silently."""

  ai_moderation_on_publish: bool = True
  """Run content moderation before publishing"""

  ai_moderation_on_fetch: bool = True
  """Run content moderation before fetching"""

  ai_ranking_interval: float = 60.0
  """Seconds between AI-driven peer ranking updates"""

  ai_ranking_confidence_threshold: float = 0.7
  """Minimum confidence for AI ranking hints to influece per selection"""

  # --- Timeouts and limits ---
  graceful_shutdown_timeout: float = 30.0
  """Seconds to wait for in-flight operation during shutdown"""

  max_metadata_keys: int = 64
  """Maximum number of key-value pairs in manifest metadata."""

  max_metadata_value_bytes: int = 1024
  """Maximum byte length of a single metadata value."""
```

**TOML file format**

When loaded from a file (`--config`), the configuration uses TOML with section headers matching the field groupings:

```toml
data_dir = "~/.tessera"
bind_address = "0.0.0.0"
bind_port = 9100

[chunking]
tessera_size = 262144

[swarm]
max_peers_per_swarm = 50
max_swarms_per_node = 10
eviction_threshold - 0.2
starvation_timeout = 120.0

[transfer]
max_requests_per_peer = 5
max_requests_per_swarm = 20
request_timeout = 30.0

[scoring]
weight_latency = 0.3
weight_failure = 0.4
weight_throughput = 0.3

[discovery]
backends = ["tracker"]
tracker_urls = ["https:tracker.example.com/announce"]

[ai]
enabled = True
ai_moderation_on_publish = true
ai_moderation_on_fetch = true
```

**Configuration precedence**

Values are resolved in order (later wins):

1. **Dataclass defaults** — the values shown above
2. **TOML file** — loaded from the path given to `--config`.
3. **CLI flagks** — `--data-dir`, `--bind`, `--tracker`, etc.
4. **Constructor arguments** — fields set directly on `TesseraConfig()` in code.

CLI flags and constructor arguments occupy the same precedence tier. In practice they do not conflict — CLI flags are only present when running from the terminal, and constructor arguments are only present when using the library API.

---

## Error Handling

All Tessera exceptions inherit from a single base class. Callers can catch `TesseraError` to handle any Tessera failure, or catch specific subclasses for fine-grained control.

**Exception Hierarchy**

```txt
TesseraError
|— ModerationError
|— CapacityError
|— StarvationError
|— IntegrityError
|— ProtocolError
|    |— HandshakeError
|    |— MessageError
|— ConfigError
```

```python
class TesseraError(Exception):
  """Base class for all Tessera exceptions."""

class ModerationError(TesseraError):
  """Content moderation rejected the operation.
  Attributes:
    reason: Human-readable explanation for the moderation adapter.
    manifest_hash: The manifest hash involved, if available.
  """
  reason: str
  manifest_hash: bytes | None

class CapacityError(TesseraError):
  """Node capacity exhausted
  Raised when max_swarms_per_node is reached and a new publish() or fetch() is attempted.

  Attributes:
    current: Number of active swarms
    maximum: The configured limit
  """
  current: int
  maximum: int

class StarvationError(TesseraError):
  """No peers found within the starvation timeout.

  Raised by fetch() when the swarms has zero peers for longer than config.starvation_timeout seconds, after exhausting exponential backoff re-discovery attempts.

  Attributes:
    manifest_hash: the mosaic that could not be fetchced.
    elapsed: seconds spent waiting
  """
  manifest_hash: bytes
  elapsed: float

class IntegrityError(TesseraError):
  """Whole-file verification failed.

  Raised by fetch() after the file is fully assembled but the SHA-256 of the reconstructed file does not match the manifest's file_hash. All per-tessera hashes passed — this indicates a Chunker/Assembler bug or manigest that was built from a different file version.

  Attributes:
    manifest_hash: The mosaic's manifest hash
    expected: The file hash declared in the manifest
    actualy: The hash of the assembled file
  """
  manifest_hash: bytes
  expected: bytes
  actual: bytes

class ProtocolError(TesseraError):
  """Wire protocol violation.
  Base class for errors detected during peer communication.

  Attributs:
    peer_id: The AgentId of the peer that caused the error.
    error_code: The wire protocol error code.
  """
  peer_id: bytes
  error_code: int

class HandshakeError(ProtocolError):
  """Handshake failed or was rejected."""

class MessageError(ProtocolError):
  """Received a malformed or unexpected message."""

class ConfigError(TesseraError):
  """Invalid configuration.

  Raised during TesseraNode construction if TesseraConfig contains invalid or contradictory values.

  Attributes:
    field: The config field name.
    reason: Why the value is invalid.
  """
  field: str
  reason: str
```

**Recoverability**

| **Exception** | **Recoverable?** | **Recommended Action** |
| ------------- | ---------------- | ---------------------- |
| `ModerationError` | No | Inform user, Do not retry with the same content |
| `CapacityError` | Yes | Wait for an active swarm to finish, or cancel one |
| `StarvationError` | Maybe | Retry later — the mosaic may not have any online seeders. |
| `IntegrityError` | No | The manifest or file data is corrupt. Do not trust the output |
| `ProtocolError` | Yes | The peer is misbehaving. The Swarm Manager evicts automatically; the transfer continues with other peers. |
| `ConfigError` | No | Fix the configuration and restart |

**Error propagation**

- **Within library.** Internal components (Transfer Engine, Swarm Manager) raise domain-specific exceptions. The `TesseraNode` methods catch internal errors and re-raise them as the public exceptions listed above. Internal exceptions types are not exported.
- **In the CLI.** The CLI runner catches all `TesseraError` subclasses, prints a human-readable message, and exits with the appropriate exit code.
- **Cancellation.** `asyncio.CancelledError` is never wrapped. If the caller cancels a task, the cancellation propagates cleanly. In-flight piece requests are allowed to complete or time out during draining.

---

## Event Callbacks

Tessera exposes three event hooks. These allow callers to react to lifecycle events without polling.

**Registering callbacks**

Callbacks are set on `TesseraNode` after construction:

```python
node = TesseraNode(config)
node.on_manifest_created = my_publish_handler
node.on_manifest_received = my_fetch_handler
node.on_transfer_complete = my_completion_handler
await node.start()
```

All callbacks are optional. If not set, the event is silently ignored.

**on_manifest_created**

```python
on_manifest_created: Callable[[ManifestEvent], None] | None = None
```

Fired after `publish()` builds and signs the manifest, before announcing to discovery. The callback receives:

```python
@dataclass
class ManifestEvent:
  manifest_hash: bytes
  """The 32-bytes manifest hash"""

  file_path: Path
  """Size of the source file in bytes."""

  tessera_count: int
  """Number of tesserae the file was chunked into"""

  metadata: dict[str, str]
  """The metadata that will be embedded in the manifest"""
```

Use case: logging, analytics, triggering external notifications when a file is published.

**`on_manifest_received`**

```python
on_manifest_received: Callable[[ManifestEvent], None] | None = None
```

Fired after `fetch()` receives and validates a manifest from a peer, before piece transfer begins. The `ManifestEvent` is the same dataclass — `file_path` is the intended output path.

Use case: pre-allocation of disk space, UI updates showing file metadata, agent decision-making about whether to proceed with the download.

**`on_transfer_complete`**

```python
on_transfer_complete: Callable[[TransferCompleteEvent], None] | None = None
```

Fired after a fetch completes successfully — all tesserae validated, file assembled, whole-file hash confirmed.

```python
@dataclass
class TransferCompleteEvent:
  manifest_hash: bytes
  """The mosaic's manifest hash."""

  output_path: Path
  """Path to the assembled file on disk"""

  file_size: int
  """Size of the assembled file in bytes"""

  elapsed: float
  """Total transfer time in seconds"""

  peer_used: int
  """Number of distinct peers that contributed pieces."""

  average_throughput: float
  """Average throughput in bytes per second over the transfer"""
```

Use case: post-download processing, chaining fetches in an agent workflow, audit logging.

**Callback semantics**

- **synchronous.** Callbacks are plain functions, not coroutines. They are invoked via `asyncio.get_event_loop().call_soon()` so they do not block the transfer. IF a callback needs to perform async work, it should schedule a task internally.
- **Non-blocking contract.** Callbacks must return promptly. A callback that blocks will delay event processing for all swarms on the node.
- **Exception isolation.** If a callback raises, the exception logged at `warning` level and swallowed. Callback failurs never abort transfer.
- **Threading.** Callbacks are always invoked on the asyncio event loop thread. No synchronization is needed for single-threaded callers.

**Progress callback (fetch-specific)**

The `on_progress` parameter on `fetch()` is not node-level hook — it is per-transfer. It receives `TransferStatus` after each verified tessera. The same semantics apply: synchronous, non-blocking, exception-isolated.

---

# Storage & State

## Purpose & Scope

This document defines how Tessera persists data to disk — where files go, how they are organized, and how state is recovered where files go, how they are organized, and how state is recovered after a crash or restart. It is the owner of `data_dir` and the authority on every file and directory Tessera creates.

**What this spec defines**

- **Directory layout** The structure under `data_dir` (`~/.tessera` by default). Where manifests, tesserae, transfer rate, and logs are stored.
- **Manifest store.** How serialized manifests are persisted and looked up by manifest hash.
- **Tessera store.** How downloaded and locally-chunked tesserae are stored on disk, including partial pieces and completed pieces.
- **Transfer state & resume.** The on-disk representation of in-progress transfers — bitfields, peer lists, retry counts — that enables resumption after a node restart without re-downloading completed pieces.
- **Concurrency & Crash recovery.** How concurrent reads/writes to the stored are coordinates, and how the store self-heals after an unclean shutdown (killed process, power loss, disk full).
- **Garbage collection.** When and how completed transfers, orphaned tesserae, and expired manifests are cleaned up.

**Design Principles**

- **Resumable by default.** A node that crashes mid-transfer and restarts should resume from where it left off, not re-download everything. This is the single most important property of the storage layer.
- **No external dependencis.** The store uses flat files and atomic filesystem operations. No database, no WAL library, no dependency beyond Python's standard library and the OS filesystem
- **Crash-safe writes.** Every mutation follows a write-to-temp-then-rename pattern. A crash at any point leaves the store in a consistent state — either the old data or the new data, never a partial write.
- **Content-addressable.** Tesserae and manifests are stored by their hash. Duplicate detection is free — if the file exists at the expected path, it is already correct.

---

## Directory Layout

All Tessera state lives under `data_dir` (default `~/.tessera`). The directory is created on first `TesseraNode.start()` if it does not exist.

```txt
~/.tessera/
  ├── manifests/                  # Manifest store
  │   ├── a3/
  │   │   └── a3f2...c891.manifest
  │   └── b8/
  │       └── b8e1...4d20.manifest
  ├── tesserae/                   # Tessera store (per-mosaic)
  │   ├── a3f2...c891/
  │   │   ├── 000000.piece
  │   │   ├── 000001.piece
  │   │   └── ...
  │   └── b8e1...4d20/
  │       └── ...
  ├── transfers/                  # Active transfer state
  │   ├── a3f2...c891.state
  │   └── b8e1...4d20.state
  ├── tmp/                        # Temporary files (atomic writes)
  └── node.id                     # Persistent node identity
```

**Path conventions**

- **Manifest paths** use a 2-character hex prefix directory (first byte of the hash) to avoid large flat directories. File name is full hex-encoded manifest hash with `.manifest` extension.
  - Exampe: hash `a3f2...c891` → `manifests/a3/a3f2...c891.manifest`
- **Tessera paths** are grouped by mosaitc (manifest hash). Each tessera is naed by its zero-padded 6-digit deccimal index with `.piece` extension.
  - Exampe: tessera 42 of mosaic `a3f2...c891` → `tessera/a3f2...c891/000042.piece`
- **Transfer state** files are named by manifest hash with `.state` extension. One file per active or paused transfer.
- **Temporary files** are created in `tmp/` with a random suffix. Every write operation targets `tmp/` first, then renmaes to the final path. The `tmp/` directory is cleaned on startup — any files found there are remnants of interrupted writes and are deleted.

**node.id**

A 32-byte file containing the node's persistent identity seed. Created once on first startup via `os.urandom(32)`. Used to derive determinstic values that must surrvive restarts (e.g., tracker announces tokens). This is not an MFP agentId — The MFP agent is creaded fresh each session. `node.id` is a Tessera-level concept for correlating sessions.

**Permissions**

Tessera creates directories with `0o700` and files with node `0.600`. The `data_dir` contains cryptographic material (`node.id`) and download content — it should not be world-readable.

---

## Manifest Store

The manifest store persists serialized manifests so they survive node restarts. A manifest is written once and never modified.

**Write path**

1. Serialize the manifest to its binary format.
2. Compute the SHA-256 hash of the serialized bytes — this is the manifest hash
3. Derive the storage path: `manifest/{hash[0:2]}/{hash_hex}.manifest`
4. If the file alreadt exists at that path, skip — the manifest is already stored. Content-addressability guarantees correctness.
5. Write the serialized bytes to `tmp/{random}.manifest`
6. `os.rename()` the temp file to the final path. On POSIC, this is atomic.

**Read Path**

1. Derive the storage path from the manifest hash.
2. Read the file. If it does not exist, return `None`.
3. Verify: Compute SHA-256 of the bytes read and compare to the expected hash. If they differ, the file is corrupt — delete it and return `None`.

The verification step on read defends against silent disk corruption. The caller (typically the Transfer Engine) treats a missing manifest the same as a corrupt one — re-request from peers.

**Manifest Index**

The manifest store maintains an in-memory index for AI Discovery Adapter. The index map manifest hashes to their metadata key-value pairs, enabling natural-language search without deserializing every manifest on disk.

```python
class ManifestIndex:
  """In-memory index of manifest metadata, rebuilt on startup"""

  def rebuild(self) -> None:
    """Scan manifests/ and extract metadata from each file"""

  def add(self, manifest_hash: bytes, metadata: dict[str, str]) -> None:
    """Add a manifest to the index (called after write)"""

  def remove(self, manifest_hash: bytes) -> None:
    """Remove a manifest from the index (called during GC)"""

  def all_metadata(self) -> list[tuple[bytes, dict[str, str]]]:
    """Return all (hash, metadata) pairs for LLM search."""
```

The index is rebult from disk on every `TesseraNode.start()`. It is not persisted — the manifests themselves are the source of truth. Rebuild cost is linear in the number of stored manifests; at the target scale (tens to hundreds of mosaics), this completes in milliseconds.

**Disk budget**

A manifest is small — the fixed header is 60 bytes, metadata is typically under 1 KB, and the leaf hash array is `32 x tessera_count` bytes. A 1 GB file chunked at 256 KB produces ~4,000 tesserae, yielding a ~~128 KB manifest. The manifest store will not be a meaningful consumer of disk space.

---

## Tessera Store

The tessera store holds the actual file chunks — both locally-chunked pieces (publisher) and downloaded pieces (fetcher). It is the largest consumer of disk space and the most write-intensive component.

**Storage layout**

Tesserae are grouped by mosaic. Each mosaic gets a directory named by its full hex-encoded manifrst hash under `tesserae/`

File names are the zero-padded 6-digit decimal tessera index. This support mosaics up to 999,999 tessera (256 KB x 999,999 - 244 GB), well beyond typical use at the target scale.

**Write path(download)**

1. Receive piece data from a peer via PIECE message
2. Compute SHA-256 of the piece data.
3. Compute against the expected leaf hash from the manifest. If mismatch, discard and report to peer scoring
4. Write piece data to `tmp/{random}.piece`
5. `os.rename()` to `tesserae/{manifest_hash_index}/{index:06d}.piece`
6. Update the in-memory bitfield and transfer state.

If the target file already exists, the write is skipped. This handles duplicate deliveries during endgame mode without redundant I/O.

**Write path(publish)**

1. The Chunker reads the source file and yields tesserae sequentially.
2. Each tessera is hashed and writte to `tesserae/{manifest_hash_index}/{index:06d}.piece` via the same temp-then-rename pattern.
3. The leaf hashes are collected to build the manifest.

The publisher's tesserae are identical to what a fetcher would download — the store is symmetric.

**Read path**

1. Derive the path from manifest hash and tessera index.
2. Read the file. If it does not exist, return `None` (the tessera has not been downloaded yet)
3. No hash verification on read by default. The tessera was verified on write; re-verification on every read would be prohibitively expensive during assembly. The whole-file verification after assembly catches any disk corruption that occurs between write and read.

**Assembly**

When all tesserae for a mosaic are present (bitfield is complete):

1. Open the output file for writing
2. Iterate tessera indices 0 through N+1
3. Read each `.piece` file and append to the output file
4. Compute SHA-256 of the complete output file
5. Compare against the manifest's `file_hash`. If mismatch, raise `IntegrityError`
6. On success, fire the `on_transfer_complete` callback

Assembly reads are sequential, which is optimal for both spinning disks and SSDs. The Assembler does not need to seek.

**Disk usage**

The tessera store holds a full copy of every mosaic the node is seeding or downloading. For a fetcher, disk usage equals the sum of all active and completed mosaic sizes. For a publisher, the tessera duplicate the source file's content on disk, Garbage collection reclaims space for completed transfers the node no longer seeds.

---

## Transfer State & Resume

Transfer state files enable resumption after a crash or restart. Each active transfer (publish or fetch) has a corresponding `.state` file in `transfers/`

**State file format**

Transfer state is serialized as a JSON object. JSON is chosen over a binary format because state files are small, human-inspectable for debugging, and written infrequently relative to piece I/O.

```json
{
  "version": 1,
  "manifest_hash": "a3f2...c891",
  "role": "fetcher",
  "tessera_count": 200,
  "bitfield": "///////8AAAAAAAAAAAAAAAAAAAAAAA",
  "created_at": "2026-03-17T14:30:00Z",
  "bytes_downloaded": 41943050,
  "retry_counts": {"142": 2, "187": 1},
  "stuck_tesserae": [],
  "peers_seen": ["agent_id_hex_1", "agent_id_hex_2"]
}
```

| **Field** | **Type** | **Description** |
| --------- | -------- | --------------- |
| `version` | int | State file format version. Always `1` |
| `manifest_hash` | str | Hex-encoded manifest hash |
| `role` | str | `seeder` or `fetcher` |
| `tessera_count` | int | Total number of tesserae in the mosaic |
| `bitfield` | str | Base64-encoded bitfield. Bit is set if tessera is on disk |
| `created_at` | str | ISO 8601 timestamp of transfer start. |
| `updated_at` | str | ISO 8601 timestamp of last state write |
| `bytes_downloaded` | int | Total bytes written to tessera store for this mosaic |

**Write policy**

State files are not written after every piece. The overhead serializing and renaming of every tessra completion would dominate I/O for fast transfers. Instead, state is persisted:

1. **On significant progress** — every 5% of total tesserae completed (configurable as a complie-time constant, not a TesseraConfig field)
2. **On swarm state transitions** — when the swarm moves to DRAINING or CLOSED
3. **On graceful shutdown** — during `TesseraNode.stop()`, before the MFP agent unbinds
4. **On retry escalation** — when a tessera's retry count crosses `max_retries_per_tessera / 2`, to capture the anomally

In the worst case (crash between state writes), the node loses awareness of at most 5% of completed tesserae. On resume, it discovers them on disk and does not re-download them.

**Write path**

1. Build the JSON object from in-memory transfer state.
2. Serialize to bytes
3. Write to `tmp/{random}.state`
4. `os.rename()` to `transfers/{manifest_hash_hex}.state`

**Resume on startup**

When `TesseraNode.start()` is called:

1. Scan `transfers/` for `.state` files
2. For each state file:
a. Parse the JSON. If malformed, log a warning and delete the file
b. Verify the corresponding manifest exists in the manifest store. If not, the transfer cannot resume — delete the state file and its tessera directory.
c. Rebuild the bitfield from disk: scan `tesserae{manifest_hash_hex}/` and set bit i for every `{i:06d}.piece` file that exists and passes hash verification against the manifest.
d. The disk-derived bitfield is authoritative — it may have more bits set than the state file's bitfield (pieces completed after the last state write) or fewer (if a piece file was lost to disk corruption)
e. If the disk-drived bitfield is complete, the transfer is already done. Run assembly and delete the state file.
f. Otherwise, restore the transfer as a paused swarn. The swarm manager re-announces to discovery and resumes piece selection from the updates bitfield.

**Seeder state**

Publishers also get state file with `role: seeder`. The bitfield is always complete (all bits set). The state file's purpose is to tell the node on restart which mosaics to re-announce and seed. A seeder state file is deleted when the user cancels seeding or garbage collection removes the mosaic.


