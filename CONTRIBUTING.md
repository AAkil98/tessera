# Contributing to Tessera

Thank you for your interest in contributing to Tessera! This document provides guidelines for contributing to the project.

## Development Setup

```bash
git clone https://github.com/Madahub-dev/tessera.git
cd tessera
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Code Quality

All code must pass these checks before merging:

```bash
# Linting
ruff check .

# Formatting
ruff format --check .

# Type checking (strict mode)
mypy tessera/ --strict

# Tests
pytest tests/unit/
```

## Coding Standards

- **Python 3.11+** required
- **Type annotations** on all public functions and methods
- **`from __future__ import annotations`** at the top of every module
- **Ruff** for linting and formatting (line length 88, double quotes)
- **mypy strict** must pass with no errors
- Follow existing code patterns in the relevant layer

## Testing

Tests are organized by category:

| Directory | Purpose | When to run |
|-----------|---------|-------------|
| `tests/unit/` | Pure logic, no I/O | Always |
| `tests/integration/` | Real filesystem | PRs |
| `tests/e2e/` | Multi-node transfers | PRs |
| `tests/adversarial/` | Fault injection, security | PRs |
| `tests/ai/` | AI adapter tests (mock LLM) | PRs |
| `tests/benchmarks/` | Performance validation | Advisory |

Mark tests with the appropriate pytest marker (`@pytest.mark.unit`, etc.).

Use deterministic test data from `tests/fixtures.py` (seeded PRNG, seed=42).

## Pull Request Process

1. Fork the repository and create a branch from `development`
2. Make your changes with clear, focused commits
3. Ensure all CI checks pass (lint, type check, tests)
4. Update documentation if you change public API
5. Open a PR against `development` with a clear description

## Specifications

Tessera is built against 13 technical specifications in `specs/`. If your change relates to a spec, reference it in your PR description (e.g., "Implements ts-spec-006 section 4").

## Architecture

See the [README](README.md#architecture) for the layer model. Changes should respect layer boundaries:

- **Content Layer** (`tessera/content/`) - Chunking, Merkle trees, manifests
- **Wire Layer** (`tessera/wire/`) - Binary protocol messages
- **Transfer Layer** (`tessera/transfer/`) - Piece selection, peer scoring
- **Swarm Layer** (`tessera/swarm/`) - Peer discovery, capacity
- **Storage Layer** (`tessera/storage/`) - Crash-safe persistence
- **Bridge Layer** (`tessera/bridge/`) - AI adapters
- **API Layer** (`tessera/node.py`, `tessera/cli.py`) - Public interface

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
