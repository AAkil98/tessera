# Tessera

Secure peer-to-peer file sharing built on the Mirror Frame Protocol and madakit.

## What This Is

A torrent-inspired file sharing system where every peer is cryptographically authenticated, every chunk is end-to-end encrypted, and AI provides the intelligence layer for content discovery, routing, and moderation.

## What This Is Not

- Not a BitTorrent client or compatible with the BitTorrent protocol
- Not a general-purpose CDN or object store
- Not a replacement for centralized file hosting

## Built On

- **[Mirror Frame Protocol (MFP)](../mirror-frame-protocol)** — Secure P2P communication backbone. Provides encrypted bilateral channels, agent lifecycle, temporal ratchet anti-replay, federation transport, and wire protocol.
- **[madakit](../mada-modelkit)** — Composable AI/LLM interface. Provides intelligent content discovery, smart peer/piece selection, content moderation, and multi-provider middleware stack.

## Status

**Implementation complete — ready for alpha testing.**

All 13 specification documents are complete and the implementation is finished. All 9 phases from [IMPLEMENTATION.md](IMPLEMENTATION.md) are complete with 318 tests passing. See [AUDIT.md](AUDIT.md) for the comprehensive codebase audit and readiness assessment.

## Specification Documents

| # | Document | Status |
|---|----------|--------|
| 1 | Vision & Scope | Complete |
| 2 | Glossary | Complete |
| 3 | Threat Model | Complete |
| 4 | System Architecture | Complete |
| 5 | Wire Protocol Addendum | Complete |
| 6 | Content Addressing Spec | Complete |
| 7 | Swarm & Peer Discovery | Complete |
| 8 | Piece Selection & Transfer Strategy | Complete |
| 9 | AI Integration Spec | Complete |
| 10 | API & CLI Design | Complete |
| 11 | Storage & State Management | Complete |
| 12 | Performance Budget | Complete |
| 13 | Test & Validation Plan | Complete |

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.

Copyright 2026 Akil Abderrahim
