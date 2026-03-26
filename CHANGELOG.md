# Changelog

All notable changes to Tessera are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-26

### Added
- `__version__` attribute in `tessera` package
- `--version` CLI flag
- CHANGELOG.md
- MIGRATION.md (upgrade guide from 0.1.0-alpha)
- Version-consistency CI check (`__version__` must match `pyproject.toml`)

### Changed
- `pymfp` dependency bumped from `>=0.1.0` to `>=1.0.0`
- All 13 specification documents finalized (`status: draft` -> `status: stable`)
- README updated to reflect stable release status
- Config comments updated to reference MFP 1.0.0 defaults

### Removed
- `specs/draft.md` (obsolete early draft, superseded by numbered specs 01-13)

### Compatibility Notes
- Wire protocol version remains `0x0001` (no wire-breaking changes)
- Manifest format version remains `0x0001` (no format changes)
- Transfer state file version remains `1` (no state format changes)
- `TesseraNode` and `TesseraConfig` public API unchanged from 0.1.0-alpha
- `_DEFAULT_MAX_PAYLOAD` (1 MB) already aligned with MFP 1.0.0's
  `RuntimeConfig.max_payload_size` default

## [0.1.0-alpha] - 2026-03-19

### Added
- Initial alpha release
- Complete implementation across 7 layers (content, wire, transfer, swarm,
  storage, bridge, API)
- 318 tests across 6 categories (unit, integration, E2E, adversarial, AI,
  benchmarks)
- 13 technical specification documents
- CLI with publish, fetch, query, status, cancel commands
- AI-enhanced content discovery via madakit integration
