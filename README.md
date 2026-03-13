# mada-swarm

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

**Pre-implementation — specification phase.**

We are drafting the specification documents before writing any code. Progress is tracked in [SPECS_BUILD.md](SPECS_BUILD.md).

## Specification Documents

| # | Document | Status |
|---|----------|--------|
| 1 | Vision & Scope | Not started |
| 2 | Glossary | Not started |
| 3 | Threat Model | Not started |
| 4 | System Architecture | Not started |
| 5 | Wire Protocol Addendum | Not started |
| 6 | Content Addressing Spec | Not started |
| 7 | Swarm & Peer Discovery | Not started |
| 8 | Piece Selection & Transfer Strategy | Not started |
| 9 | AI Integration Spec | Not started |
| 10 | API & CLI Design | Not started |
| 11 | Storage & State Management | Not started |
| 12 | Performance Budget | Not started |
| 13 | Test & Validation Plan | Not started |

## License

TBD
