# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | Yes                |
| < 1.0   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in Tessera, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email security concerns to the maintainers with:

1. A description of the vulnerability
2. Steps to reproduce the issue
3. The potential impact
4. Any suggested fix (optional)

We will acknowledge receipt within 48 hours and aim to provide an initial assessment within 5 business days.

## Threat Model

Tessera's threat model is documented in [specs/03-threat-model.md](specs/03-threat-model.md) and covers 10 threat scenarios including:

- Man-in-the-middle attacks (mitigated by MFP encryption)
- Content poisoning (mitigated by per-chunk hash verification)
- Manifest tampering (mitigated by content-addressed identity)
- Sybil attacks (mitigated by peer scoring and capacity limits)
- Prompt injection (mitigated by sanitization filters)

## Security Design Principles

- **Authenticated peers**: Every peer is cryptographically verified via MFP
- **End-to-end encryption**: All data in transit is encrypted
- **Content addressing**: Files identified by their content hash
- **Zero-trust verification**: Every piece is hash-verified on receipt
- **Sandboxed AI**: Intelligence Bridge isolates LLM interactions

## Dependencies

Tessera's security depends on:

- **pymfp** for cryptographic identity and encrypted channels
- **madakit** (optional) for AI features, sandboxed via the Bridge layer
