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
| 5 | Wire Protocol Addendum | Not started | — | — | |
| 6 | Content Addressing Spec | Not started | — | — | |
| 7 | Swarm & Peer Discovery | Not started | — | — | |
| 8 | Piece Selection & Transfer Strategy | Not started | — | — | |
| 9 | AI Integration Spec | Not started | — | — | |
| 10 | API & CLI Design | Not started | — | — | |
| 11 | Storage & State Management | Not started | — | — | |
| 12 | Performance Budget | Not started | — | — | |
| 13 | Test & Validation Plan | Not started | — | — | |

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
- [ ] **Chunk size:** Fixed vs adaptive? MFP's default max_payload is 1MB — do we match that or go smaller?
- [ ] **Tracker model:** Centralized tracker, DHT, gossip protocol, or hybrid? Impacts docs 4, 5, 7.
- [x] **Scope of AI integration:** Optional enhancement. Core transfer protocol works without it. Resolved in spec 01, section 6.
- [x] **Target scale:** Tens to hundreds of peers (private/semi-private networks). Resolved in spec 01, NG3.
- [ ] **License:** Not yet decided.

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
