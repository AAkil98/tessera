# SEED_CONTEXT — Session Continuity

This document provides full context for resuming Tessera specification work.

---

## Project Summary

**Tessera** is a secure, peer-to-peer file sharing protocol built on two existing libraries:

- **Mirror Frame Protocol (MFP)** at `../mirror-frame-protocol` — encrypted P2P agent communication
- **madakit** at `../mada-modelkit` — composable AI/LLM middleware

Repository: `/home/aakil98/mada/tessera`

## Workflow

1. **Scaffold** — User says "scaffold." Create the spec file with metadata (yaml frontmatter), table of contents, and footer. No body content. Template follows `../mada-os/TEMPLATE.md` format. Footer reads: `*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*`
2. **Write section** — User says "proceed" or "first section" etc. Draft the next section and present it as a message. Do NOT write it to the file yet.
3. **Approve** — User says "approved, pen down." Write the section to the file. Then immediately present the next section for review.
4. **Bulk approve** — User may say "pen down all remaining sections." Write the current section plus draft and write all remaining sections (including References) in one edit.
5. After completing a spec, update `SPECS_BUILD.md` (document tracker + session log) and `README.md` (status table).

Spec IDs use prefix `ts-spec-NNN`. Tags include `tessera`.

## Completed Specs (4 of 13)

| # | File | Key Decisions |
|---|------|---------------|
| 1 | `specs/01-vision-and-scope.md` | 7 goals, 5 non-goals, 6 success criteria. madakit is optional (G5, section 6). Target: tens-to-hundreds of peers (NG3). No BitTorrent compat (NG1). |
| 2 | `specs/02-glossary.md` | 11 native terms (tessera, mosaic, manifest, etc.), 10 MFP terms, 4 madakit terms, 8 redefined BitTorrent terms. |
| 3 | `specs/03-threat-model.md` | 5 trust assumptions, 7 assets, 5 actors, 10 threats, 5 MFP-inherited mitigations, 8 new mitigations, 6 out-of-scope threats. |
| 4 | `specs/04-system-architecture.md` | 4 layers, 13 subcomponents, publish flow (11 steps), fetch flow (23 steps), strict dependency boundaries, async-first concurrency, 5 extension points. |

## Remaining Specs (9 of 13)

| # | Document | Next to draft |
|---|----------|:---:|
| 5 | Wire Protocol Addendum | **<-- start here** |
| 6 | Content Addressing Spec | |
| 7 | Swarm & Peer Discovery | |
| 8 | Piece Selection & Transfer Strategy | |
| 9 | AI Integration Spec | |
| 10 | API & CLI Design | |
| 11 | Storage & State Management | |
| 12 | Performance Budget | |
| 13 | Test & Validation Plan | |

## Open Questions (from SPECS_BUILD.md)

- [ ] **Chunk size:** Fixed vs adaptive? MFP's default max_payload is 1MB.
- [ ] **Tracker model:** Centralized tracker, DHT, gossip protocol, or hybrid?
- [ ] **License:** Not yet decided.

## Review: Gaps and Improvements in Completed Specs

Before proceeding to spec 05, the following items in specs 01–04 should be reviewed and resolved.

### Glossary Gaps (ts-spec-002)

- **Missing terms from architecture spec.** Spec 04 introduced subcomponents and concepts not yet in the glossary: *Intelligence Bridge*, *Request Scheduler*, *Peer Scorer*, *Bitfield Manager*, *Swarm Registry*, *Capacity Enforcer*, *Discovery Client*, *Peer Connector*, *Chunker*, *Assembler*, *Piece Verifier*. Decide whether these are glossary-level terms or internal implementation detail that does not need formal definition.
- **Missing term: Bitfield.** Used in spec 04 data flows and referenced in the BitTorrent section of the glossary, but the Tessera-native definition (our specific bitfield format/semantics) is not formally defined.

### Threat Model Gaps (ts-spec-003)

- **Publisher signature undefined.** T3 mitigation (replay of stale manifest) references "publisher signature" and "monotonic version number" — but no spec yet defines how publishers sign manifests or what key material is used. This needs to be addressed in spec 06 (Content Addressing) or called out as a forward reference.
- **Manifest mutability tension.** T3 mitigation implies manifests can be versioned (updated), but the content addressing model (manifest hash = identity) implies immutability. If a manifest is updated, its hash changes — so it is effectively a new mosaic. Clarify: does Tessera support manifest updates for the same logical file, or is each version a distinct mosaic?

### Vision & Scope Gaps (ts-spec-001)

- **SC4 testability.** Success criterion SC4 ("discover and fetch via natural-language query") requires madakit, which is optional. Clarify whether SC4 is conditional on madakit being installed, or whether it implies a baseline discovery mechanism that also supports text queries.
- **Single file vs. multi-file mosaics.** The spec consistently refers to "a file" but never explicitly states whether a mosaic is always a single file or can represent a directory/bundle. This affects the manifest format (spec 06) and should be decided before drafting it.

### Architecture Gaps (ts-spec-004)

- **Configuration surface undefined.** The architecture references configurable values (tessera size, max concurrent requests, max peers per swarm, shutdown timeout) but does not define a configuration object or defaults. Spec 10 (API & CLI) or spec 11 (Storage & State) should own this — flag it as a forward dependency.
- **Error handling strategy.** The data flows describe the happy path and piece verification failure, but do not address: network partition mid-transfer, MFP runtime crash recovery, or partial disk write failures. Decide whether these belong in spec 04 as addenda or in spec 11 (Storage & State).
- **ADR gap.** The decision to use `asyncio` (over threading, multiprocessing, or trio) is stated in spec 04 section 7 but not recorded in the ADR log in SPECS_BUILD.md.

### Cross-Spec Consistency

- **Spec 03 references ts-spec-006 for manifest versioning, but spec 04's publish flow does not include a versioning step.** If manifest versioning is a real feature, it should appear in the publish data flow.
- **Spec 04 introduces the term "Intelligence Bridge" as a component name, but spec 01 and spec 02 do not mention it.** Either backport it to the glossary or confirm it is internal-only terminology.

---

*These items do not block drafting specs 05–13, but should be resolved before the specification phase is considered complete.*
