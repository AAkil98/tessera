# Threat Model

```yaml
id: ts-spec-003
type: spec
status: draft
created: 2026-03-13
revised: 2026-03-13
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [security, threat-model, tessera]
```

## Table of Contents

1. Trust Assumptions
2. Assets Under Protection
3. Threat Actors
4. Threat Catalog
5. Mitigations Inherited from MFP
6. Mitigations Requiring New Implementation
7. Out-of-Scope Threats
8. References

---

## 1. Trust Assumptions

Tessera's security model rests on the following assumptions. If any of these are violated, the guarantees described in this document do not hold.

| # | Assumption | Rationale |
|---|-----------|-----------|
| TA1 | **The MFP runtime is trusted.** The runtime that hosts Tessera peers is part of the trusted computing base. It correctly executes the message pipeline, enforces quarantine, and does not leak key material. | Inherited from MFP. Tessera cannot protect against a compromised runtime any more than an application can protect against a compromised OS kernel. |
| TA2 | **Cryptographic primitives are sound.** SHA-256, ChaCha20-Poly1305, X25519, and HMAC-SHA256 behave as specified and have no practical exploits. | Standard assumption for any protocol built on modern cryptography. |
| TA3 | **The manifest is obtained from a trusted source.** The initial manifest (or its hash) reaches the fetching peer through a channel the peer trusts — out-of-band sharing, a trusted discovery service, or a direct peer recommendation. | Tessera verifies integrity (hash tree) but cannot verify intent. A valid manifest for a malicious file is still a valid manifest. Trust in "what to fetch" is external to the protocol. |
| TA4 | **Peers have reliable clocks.** Clocks do not need to be synchronized across peers, but each peer's local clock must advance monotonically. | Required by MFP's temporal ratchet. A clock that jumps backward could cause valid frames to be rejected or replayed frames to be accepted. |
| TA5 | **The local filesystem is not adversarially controlled.** On-disk storage for incomplete mosaics, manifests, and peer state is not tampered with by external processes during operation. | Tessera verifies tesserae on receipt but does not continuously re-verify stored data. Post-write tampering is a host security problem, not a protocol problem. |

## 2. Assets Under Protection

| # | Asset | Description | Impact if Compromised |
|---|-------|-------------|----------------------|
| A1 | **File content** | The plaintext bytes of mosaics being transferred. | Confidentiality breach. Unauthorized parties read file contents. |
| A2 | **Manifest integrity** | The hash tree and metadata that define a mosaic. | Integrity breach. A tampered manifest could direct peers to accept wrong or malicious tesserae. |
| A3 | **Peer identity** | The AgentId that binds a peer to its cryptographic keys. | Impersonation. An attacker acts as a trusted peer, poisoning swarms or intercepting transfers. |
| A4 | **Transfer completeness** | The guarantee that a fetched mosaic matches the original file exactly. | Corruption. The assembled file is silently wrong — missing, reordered, or substituted tesserae. |
| A5 | **Swarm membership** | The set of authenticated peers in a swarm. | Infiltration. Unauthorized peers join swarms to observe, disrupt, or poison transfers. |
| A6 | **Channel key material** | Symmetric keys, ratchet state, and PRNG seeds used by MFP channels. | Total compromise. All past and future messages on that channel are readable and forgeable. |
| A7 | **Peer availability** | The ability of honest peers to participate in swarms without disruption. | Denial of service. Legitimate transfers are stalled or prevented. |

## 3. Threat Actors

| # | Actor | Capability | Motivation |
|---|-------|-----------|------------|
| AC1 | **Malicious peer** | Holds a valid AgentId and has been admitted to a swarm. Can send arbitrary payloads over their MFP channels. Cannot break encryption or forge other peers' identities. | Poison tesserae, waste bandwidth, disrupt specific transfers, exfiltrate manifest metadata. |
| AC2 | **Network observer** | Can observe encrypted traffic between peers (passive MITM position). Cannot decrypt, modify, or inject messages due to MFP's AEAD encryption. | Traffic analysis — inferring who is transferring what, swarm sizes, transfer timing. |
| AC3 | **Sybil attacker** | Can create multiple valid peer identities and join a swarm with many colluding nodes. Bounded by MFP's `max_agents` and `max_channels_per_agent` limits. | Dominate a swarm's piece availability, bias rarest-first selection, outvote honest peers in consensus. |
| AC4 | **Rogue discovery service** | Operates or has compromised the discovery service. Can return false peer lists for manifest hashes. | Redirect fetchers to malicious peers, deny discovery of legitimate swarms, map who is requesting what. |
| AC5 | **Compromised publisher** | Controls the original file and manifest. Can publish a valid manifest for malicious content. | Social engineering via file content. Tessera guarantees integrity (file matches manifest), not intent (file is safe). Partially mitigated by madakit content moderation (ts-spec-009). |

## 4. Threat Catalog

| # | Threat | Actor | Asset | Attack Description |
|---|--------|-------|-------|--------------------|
| T1 | **Piece poisoning** | AC1 | A4 | A malicious peer serves a tessera whose bytes do not match the hash in the manifest's hash tree. If accepted, the assembled mosaic is corrupted. |
| T2 | **Manifest tampering** | AC1, AC4 | A2 | An attacker modifies a manifest in transit or serves a forged manifest from a compromised discovery service. The fetcher builds an incorrect hash tree and accepts wrong tesserae. |
| T3 | **Replay of stale manifest** | AC1 | A2 | An attacker re-announces an old version of a manifest after the publisher has issued an updated one. Peers fetch an outdated mosaic believing it to be current. |
| T4 | **Sybil flooding** | AC3 | A5, A7 | An attacker joins a swarm with many identities, consuming channel slots and bandwidth. Honest peers are crowded out or slowed down. |
| T5 | **Selective piece withholding** | AC1, AC3 | A4, A7 | A peer (or colluding sybils) claims to hold tesserae via bitfield but never serves them, or serves them slowly. Fetchers waste time and channel capacity on unproductive requests. |
| T6 | **Transfer eavesdropping** | AC2 | A1 | A network observer intercepts tessera payloads in transit to read file contents. |
| T7 | **Peer impersonation** | AC1 | A3, A5 | An attacker forges another peer's AgentId to inject itself into a swarm under a trusted identity. |
| T8 | **Discovery poisoning** | AC4 | A5 | A rogue discovery service returns attacker-controlled peer lists, directing fetchers into a hostile swarm. |
| T9 | **Prompt injection via metadata** | AC1, AC5 | A2 | Manifest metadata fields (file name, description, tags) contain prompt injection payloads targeting agent peers that process metadata with an LLM. |
| T10 | **Bandwidth exhaustion** | AC1, AC3 | A7 | A peer floods requests for tesserae it does not need, or sends unsolicited tesserae, consuming the target's upload bandwidth and MFP channel capacity. |

## 5. Mitigations Inherited from MFP

These defenses are provided by MFP and require no new implementation in Tessera.

| Threat | Mitigation | MFP Mechanism |
|--------|-----------|---------------|
| T6 — Eavesdropping | All tessera payloads are encrypted end-to-end. A network observer sees only ciphertext. | ChaCha20-Poly1305 AEAD on every channel message. |
| T7 — Peer impersonation | AgentIds are cryptographically bound to channel keys. Forging an identity requires the victim's key material. | X25519 key exchange at channel bootstrap; HMAC-SHA256 frame binding. |
| T10 — Bandwidth exhaustion (partial) | Peers that exceed message rate limits are automatically quarantined. | `max_message_rate` enforcement and `quarantine_agent` in the runtime pipeline. |
| T2 — Manifest tampering (in transit) | Manifests sent over MFP channels cannot be modified in transit without detection. | AEAD authentication tag on every protocol message. |
| T3 — Replay (partial) | Replayed MFP messages are rejected because the ratchet has advanced past the frame's step counter. | Temporal ratchet with per-message state advancement. |

## 6. Mitigations Requiring New Implementation

These defenses must be built in Tessera. They are not covered by MFP.

| Threat | Mitigation | Implementation Approach |
|--------|-----------|------------------------|
| T1 — Piece poisoning | **Hash tree verification.** Every received tessera is hashed and verified against the corresponding leaf in the manifest's Merkle tree before being written to disk. Mismatches trigger immediate rejection and peer scoring penalty. | Tessera core — ts-spec-006. |
| T2 — Manifest tampering (at rest / via discovery) | **Manifest hash pinning.** Fetchers obtain the manifest hash from a trusted source (TA3). Any manifest whose SHA-256 does not match the pinned hash is rejected, regardless of source. | Tessera core — ts-spec-006. |
| T3 — Replay of stale manifest | **Manifest versioning.** Manifests include a monotonic version number and a publisher signature. Peers reject manifests with a version equal to or lower than one they have already seen for the same mosaic. | Tessera core — ts-spec-006. |
| T4 — Sybil flooding | **Swarm capacity limits.** Each swarm enforces a maximum peer count. New join requests are rejected when the limit is reached. Combined with MFP's `max_agents` and `max_channels_per_agent`, this bounds the resources any attacker can consume. | Tessera swarm manager — ts-spec-007. |
| T5 — Selective withholding | **Peer scoring and timeout.** Peers that repeatedly fail to serve requested tesserae within a deadline accumulate negative score. Below a threshold, they are deprioritized and eventually disconnected. | Tessera transfer engine — ts-spec-008. |
| T8 — Discovery poisoning | **Multi-source verification.** Fetchers query multiple discovery sources and cross-reference results. Peers returned by a single source but absent from others are treated with lower trust. Ultimately bounded by TA3 — the manifest hash itself is the root of trust, not the discovery service. | Tessera discovery — ts-spec-007. |
| T9 — Prompt injection via metadata | **Metadata sanitization.** Manifest metadata fields are treated as untrusted input. Before any LLM processing, metadata passes through a sanitization layer that strips or escapes injection patterns. When madakit is active, ContentFilterMiddleware provides an additional defense. | Tessera manifest parser + madakit integration — ts-spec-006, ts-spec-009. |
| T10 — Bandwidth exhaustion (Tessera layer) | **Request validation.** Tessera rejects requests for tessera indices that do not exist in the manifest, unsolicited tessera pushes, and duplicate requests for already-served tesserae. Combined with MFP's rate limiting, this bounds both protocol-level and application-level flooding. | Tessera transfer engine — ts-spec-008. |

## 7. Out-of-Scope Threats

These threats are acknowledged but explicitly not addressed by Tessera.

| Threat | Reason for Exclusion |
|--------|---------------------|
| **Compromised MFP runtime** | TA1 — the runtime is part of the trusted computing base. Defending against a compromised runtime would require hardware-level isolation (SGX, TrustZone), which is outside Tessera's scope. |
| **Side-channel attacks** | Timing, power, and memory access pattern analysis are excluded. Mitigating these requires constant-time implementations and hardware countermeasures beyond a Python application. |
| **Traffic analysis** | A network observer can infer swarm participation, transfer sizes, and timing from encrypted traffic patterns. Defending against this requires onion routing or mix networks, which conflict with NG2 (anonymity is a non-goal). |
| **Malicious file content** | Tessera guarantees that a mosaic matches its manifest, not that the file content is safe. A valid manifest for malware is still a valid manifest. Partial mitigation is available via madakit content moderation (ts-spec-009) but is not a protocol guarantee. |
| **Post-download exploitation** | What happens after a mosaic is assembled and written to disk — execution, parsing, rendering — is the responsibility of the consuming application, not Tessera. |
| **At-rest storage encryption** | Protecting stored tesserae and manifests on disk is a host-level concern. MFP offers optional storage encryption, but Tessera does not mandate it. |

---

## 8. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Defines goals G1–G3 (authentication, encryption, anti-replay) and non-goal NG2 (anonymity) that bound this threat model |
| R2 | ts-spec-002 — Glossary | Defines all terms used in this document |
| R3 | MFP Python Implementation (mirror-frame-protocol) | Source of inherited mitigations: AEAD encryption, ratchet, quarantine, rate limiting |
| R4 | ts-spec-006 — Content Addressing Spec | Specifies hash tree verification, manifest hash pinning, and manifest versioning |
| R5 | ts-spec-007 — Swarm & Peer Discovery | Specifies swarm capacity limits and multi-source discovery verification |
| R6 | ts-spec-008 — Piece Selection & Transfer Strategy | Specifies peer scoring, request validation, and withholding countermeasures |
| R7 | ts-spec-009 — AI Integration Spec | Specifies content moderation and metadata sanitization via madakit |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
