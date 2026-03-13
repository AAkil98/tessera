# SPECS_BUILD — Specification Build Journal

This file tracks the drafting of mada-swarm's specification documents, logs architectural decisions, and records open questions as they arise.

---

## Document Tracker

| # | Document | Status | Started | Completed | Notes |
|---|----------|--------|---------|-----------|-------|
| 1 | Vision & Scope | Not started | — | — | |
| 2 | Glossary | Not started | — | — | |
| 3 | Threat Model | Not started | — | — | |
| 4 | System Architecture | Not started | — | — | |
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
- **Context:** mada-swarm depends on two sibling libraries — MFP (secure P2P comms) and madakit (AI/LLM interface). Need to decide how they relate at the package level.
- **Decision:** mada-swarm is a standalone project that imports MFP and madakit as dependencies. It is not a plugin or extension of either. New code (chunking, swarm logic, tracker) lives entirely in this repo.
- **Status:** Accepted

### ADR-002: Specification-First Development
- **Date:** 2026-03-13
- **Context:** The intersection of encrypted P2P protocols, torrent mechanics, and AI integration has enough moving parts that jumping straight to code would create rework.
- **Decision:** Draft all 13 specification documents before writing implementation code. Documents are ordered by dependency — later specs build on decisions made in earlier ones.
- **Status:** Accepted

---

## Open Questions

- [ ] **Naming:** Is "mada-swarm" the final project name?
- [ ] **Chunk size:** Fixed vs adaptive? MFP's default max_payload is 1MB — do we match that or go smaller?
- [ ] **Tracker model:** Centralized tracker, DHT, gossip protocol, or hybrid? Impacts docs 4, 5, 7.
- [ ] **Scope of AI integration:** Core requirement or optional enhancement? Impacts doc 9 priority.
- [ ] **Target scale:** Dozens of peers or thousands? Drives performance budget (doc 12) and architecture (doc 4).
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
