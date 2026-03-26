# Vision & Scope

```yaml
id: ts-spec-001
type: spec
status: stable
created: 2026-03-13
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [vision, scope, tessera]
```

## Table of Contents

1. Problem Statement
2. Vision
3. Goals & Non-Goals
4. Target Users
5. Core Value Propositions
6. Dependency Rationale
7. Success Criteria
8. References

---

## 1. Problem Statement

Peer-to-peer file sharing remains split between two unsatisfying extremes. Public torrent networks offer decentralized transfer but provide no peer authentication, no payload encryption, and no defense against poisoned pieces or sybil participants. Private sharing solutions (cloud drives, managed transfer services) solve trust but reintroduce centralization, single points of failure, and vendor lock-in.

Neither model was designed for a world where autonomous agents — not just humans — initiate, negotiate, and execute file transfers. Agents face additional threats that traditional P2P ignores: prompt injection embedded in metadata, replay of stale manifests to trick an agent into re-downloading obsolete content, and forged peer announcements that redirect transfers to adversarial nodes.

There is no existing system that combines decentralized swarm-based transfer with cryptographic peer identity, end-to-end chunk encryption, anti-replay guarantees, and an AI-augmented intelligence layer — all as a single coherent protocol rather than bolted-on afterthoughts.

Tessera exists to fill that gap.

## 2. Vision

Tessera is a secure, agent-native, swarm-based file sharing protocol where every peer is cryptographically identified, every chunk is encrypted end-to-end, and intelligence is a first-class layer — not an afterthought.

A human or agent publishes a file. The system chunks it, builds a hash tree, and produces a manifest. Peers discover the manifest, join the swarm, and exchange pieces over MFP bilateral channels — each transfer authenticated, encrypted, and replay-proof by the protocol itself, not by application code. madakit sits above the swarm, providing intelligent piece selection, natural-language content discovery, and automated moderation.

The result is a system that inherits the resilience of decentralized swarms, the security posture of MFP, and the adaptability of AI-driven middleware — unified under a single protocol with a minimal, composable API.

## 3. Goals & Non-Goals

### Goals

- **G1: Authenticated swarm.** Every peer in a swarm is bound to a cryptographic identity via MFP. No anonymous participation.
- **G2: End-to-end chunk encryption.** Piece data is encrypted in transit between peers. Intermediaries and transport layers never see plaintext.
- **G3: Anti-replay and anti-forgery.** MFP's temporal ratchet ensures stale or forged pieces and manifests are rejected at the protocol layer, before application logic runs.
- **G4: Decentralized transfer.** Files are sourced from multiple peers simultaneously. No single peer is required to hold the complete file.
- **G5: AI-augmented operations.** Content discovery, piece prioritization, peer reputation, and moderation are driven by LLM capabilities via madakit.
- **G6: Agent-native API.** The protocol is designed to be invoked by autonomous agents as naturally as by human users.
- **G7: Composable and embeddable.** Tessera is a library first. It can be embedded in any Python process or run as a standalone daemon.

### Non-Goals

- **NG1: BitTorrent compatibility.** We do not implement or interoperate with the BitTorrent protocol, DHT, or tracker standards.
- **NG2: Anonymity.** Authenticated identity is a core guarantee. Anonymizing the network is an explicit non-goal.
- **NG3: Massive-scale public swarms.** The design targets private or semi-private networks of tens to hundreds of peers, not open internet swarms of thousands.
- **NG4: Streaming media.** Real-time audio/video streaming is out of scope. The unit of transfer is a complete file. A mosaic always represents a single file — directory or bundle sharing is not supported in v1.
- **NG5: Storage platform.** Tessera moves files between peers. It is not a distributed filesystem or persistent object store.

## 4. Target Users

- **Agent developers** building autonomous systems that need to exchange files securely without trusting a central broker. Their agents bind to Tessera as MFP agents and participate in swarms programmatically.
- **Small-team operators** running private infrastructure (research labs, internal tooling groups, edge deployments) who need decentralized file distribution with auditability and encryption — without the overhead of enterprise file sync platforms.
- **Mada ecosystem users** already running MFP runtimes or madakit stacks, for whom Tessera is a natural extension — adding file transfer capability to an environment that already handles secure agent communication and AI orchestration.

## 5. Core Value Propositions

- **Security by default, not by configuration.** Peer authentication, chunk encryption, and replay prevention are protocol guarantees — they cannot be misconfigured or skipped. This is inherited from MFP's design, where validation happens before payloads reach application code.
- **Zero-trust peer model.** Every piece received is hash-verified against the manifest. Every message is cryptographically bound to its sender. Malicious peers are quarantined automatically via MFP's rate limiting and quarantine mechanisms. Trust is proven, never assumed.
- **Intelligence as a layer.** AI capabilities (content discovery, smart peer selection, moderation) are delivered through madakit's composable middleware stack. They can be swapped, stacked, or removed without touching the transfer protocol. The swarm works without AI; AI makes it smarter.
- **Embeddable by design.** Tessera is a Python library, not a monolithic application. An agent can join a swarm, fetch a file, and leave — in a few lines of code, inside any process.

## 6. Dependency Rationale

### Mirror Frame Protocol (MFP)

Tessera does not implement its own transport, encryption, or peer identity. MFP provides all three:

| Need | MFP Capability |
|------|----------------|
| Peer identity | AgentId — 32-byte cryptographically bound identifier |
| Encrypted channels | Bilateral channels with ChaCha20-Poly1305 AEAD |
| Anti-replay | Temporal ratchet — each message advances state, old frames are permanently invalid |
| Peer lifecycle | bind/unbind with quarantine for misbehaving peers |
| Wire format | 64-byte envelope header with federation transport over TCP |
| Connection management | Connection pooling, circuit breakers, timeouts |

Building these from scratch would represent the majority of the project's complexity. MFP delivers them as a tested, production-hardened library (813 tests, ~95% coverage).

### madakit

madakit provides the AI/LLM interface layer. Tessera uses it for capabilities that benefit from language model reasoning:

| Need | madakit Capability |
|------|-------------------|
| Content discovery | Natural-language queries routed to any of 21 LLM providers |
| Smart peer selection | LLM-driven ranking via composable middleware |
| Content moderation | ContentFilterMiddleware for safety checks before sharing |
| Resilience | RetryMiddleware, CircuitBreakerMiddleware, FallbackMiddleware |
| Cost control | CostControlMiddleware with budget limits and alerts |

madakit is an optional enhancement. The core transfer protocol functions without it. When present, it is accessed exclusively through its `BaseAgentClient` interface — no provider lock-in.

## 7. Success Criteria

- **SC1:** Two MFP-bound agents can exchange a file of at least 100 MB over a swarm, with every piece encrypted, hash-verified, and replay-protected — without either agent handling cryptography directly.
- **SC2:** A file can be sourced from three or more peers simultaneously, with the transfer completing faster than fetching from any single peer alone.
- **SC3:** A poisoned piece (corrupted or forged) from a malicious peer is detected and rejected at the protocol layer. The malicious peer is quarantined. The transfer completes from honest peers.
- **SC4:** When madakit is installed, an agent can discover and fetch a file using a natural-language query, without knowing the manifest hash in advance. Without madakit, fetchers must obtain manifest hashes through out-of-band means or direct peer recommendation.
- **SC5:** The library API allows a complete publish-discover-fetch cycle in under 20 lines of application code.
- **SC6:** All of the above work identically whether peers are in the same MFP runtime or federated across separate runtimes.

## 8. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | MFP Specification (mfp-spec) | Core protocol that Tessera builds on for transport, encryption, and peer identity |
| R2 | MFP Python Implementation (mirror-frame-protocol) | Production implementation of MFP; direct dependency |
| R3 | madakit (mada-modelkit) | AI/LLM middleware layer; optional dependency |
| R4 | BitTorrent Protocol Specification (BEP 3) | Reference design for swarm-based file transfer; Tessera is informed by but not compatible with this protocol |
| R5 | ts-spec-003 — Threat Model | Companion spec; detailed threat analysis for Tessera |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
