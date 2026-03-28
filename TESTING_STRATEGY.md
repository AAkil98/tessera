# Tessera Testing Strategy: Complete Branch Coverage

**Baseline:** 730 tests | 99% line coverage | 100% branch coverage | 2,417 statements | 548 branches

---

## Current Coverage Gaps

| Module | Lines | Branch | Missing | Gap Type |
|--------|-------|--------|---------|----------|
| `tessera/__main__.py` | 0% | 50% | 3-6 | Entry point guard |
| `tessera/discovery/tracker.py` | 96% | 100% | 64 | httpx ImportError |
| `tessera/storage/manifest_store.py` | 97% | 100% | 117-119 | Write crash recovery |
| `tessera/storage/tessera_store.py` | 97% | 100% | 64-66 | Write crash recovery |
| All other modules (27) | 100% | 100% | - | - |

**Total uncovered: 10 lines across 4 modules.**

---

## Phase 1 — Storage Write Failure Recovery (HIGH priority)

**Target:** `manifest_store.py:117-119`, `tessera_store.py:64-66`

Both modules use the write-to-tmp-then-rename pattern for crash safety (ts-spec-011). The `except BaseException` cleanup paths are untested.

### Tests to add

**File:** `tests/integration/test_write_failure_recovery.py`

| Test | What it covers |
|------|----------------|
| `test_manifest_store_rename_failure_cleans_tmp` | Monkeypatch `os.rename` to raise `OSError`; verify tmp file removed, exception re-raised |
| `test_manifest_store_write_bytes_failure_cleans_tmp` | Monkeypatch `Path.write_bytes` to raise; verify tmp file removed |
| `test_tessera_store_rename_failure_cleans_tmp` | Same pattern for piece writes |
| `test_tessera_store_write_bytes_failure_cleans_tmp` | Same pattern for piece writes |
| `test_write_failure_does_not_corrupt_existing` | Verify a pre-existing valid file survives a failed overwrite attempt |
| `test_concurrent_write_failure_isolation` | Two concurrent writes, one fails — the other succeeds cleanly |

**Approach:** `monkeypatch` on `os.rename` or `Path.write_bytes` to inject `OSError("Disk full")`. Assert temp file is cleaned up via `tmp_path` inspection and that the original exception propagates.

**Expected impact:** +6 lines covered. Line coverage 99% -> 99.75%.

---

## Phase 2 — Optional Dependency Error Path (MEDIUM priority)

**Target:** `tracker.py:64`

The httpx ImportError path fires when the optional `[tracker]` extra isn't installed.

### Tests to add

**File:** `tests/unit/test_tracker.py` (extend existing)

| Test | What it covers |
|------|----------------|
| `test_tracker_init_without_httpx` | Patch `httpx` out of `sys.modules`, instantiate `TrackerBackend` without `client=`, verify `ImportError` with install instructions |

**Approach:** Use `monkeypatch.setitem(sys.modules, 'httpx', None)` or `monkeypatch.delitem` to simulate missing httpx. Alternatively, mark with `# pragma: no cover` if environment manipulation is too fragile.

**Expected impact:** +1 line covered.

---

## Phase 3 — Entry Point (LOW priority)

**Target:** `__main__.py:3-6`

Standard `if __name__ == "__main__"` guard. The `main()` function it calls is already 100% covered (78 branches).

### Tests to add

**File:** `tests/test_cli.py` (extend existing)

| Test | What it covers |
|------|----------------|
| `test_python_m_tessera_invocation` | `subprocess.run(["python", "-m", "tessera", "--help"])`, assert exit code 0 and output contains usage |

**Approach:** Subprocess invocation. Adds process startup overhead but is the only way to exercise `__main__`.

**Alternative:** Accept as-is and add `# pragma: no cover`. The guarded code is trivial.

**Expected impact:** +3 lines covered. Total line coverage -> ~99.9%.

---

## Phase 4 — Partial Branch Elimination

The coverage report shows 1 partial branch across the entire codebase. To find and close it:

1. Run `pytest --cov=tessera --cov-report=html --cov-branch` and inspect the HTML report for yellow-highlighted lines (partial branches).
2. Identify the condition and add a test exercising the missing path.
3. Likely in a compound `if` or `try/except` with multiple exception types.

---

## Module-by-Module Target Matrix

Every source module must reach **100% line + 100% branch** (or carry an explicit `# pragma: no cover` with justification).

| Module | Current | Target | Action |
|--------|---------|--------|--------|
| `__init__.py` | 100/100 | 100/100 | Done |
| `__main__.py` | 0/50 | pragma | Phase 3 or pragma |
| `node.py` | 100/100 | 100/100 | Done |
| `cli.py` | 100/100 | 100/100 | Done |
| `config.py` | 100/100 | 100/100 | Done |
| `errors.py` | 100/100 | 100/100 | Done |
| `types.py` | 100/100 | 100/100 | Done |
| `bridge/bridge.py` | 100/100 | 100/100 | Done |
| `bridge/discovery_adapter.py` | 100/100 | 100/100 | Done |
| `bridge/ranking_adapter.py` | 100/100 | 100/100 | Done |
| `bridge/selection_adapter.py` | 100/100 | 100/100 | Done |
| `bridge/moderation_adapter.py` | 100/100 | 100/100 | Done |
| `bridge/sanitizer.py` | 100/100 | 100/100 | Done |
| `content/bitfield.py` | 100/100 | 100/100 | Done |
| `content/chunker.py` | 100/100 | 100/100 | Done |
| `content/manifest.py` | 100/100 | 100/100 | Done |
| `content/merkle.py` | 100/100 | 100/100 | Done |
| `discovery/backend.py` | 100/100 | 100/100 | Done |
| `discovery/client.py` | 100/100 | 100/100 | Done |
| `discovery/tracker.py` | 96/100 | 100/100 | Phase 2 |
| `storage/layout.py` | 100/100 | 100/100 | Done |
| `storage/manifest_store.py` | 97/100 | 100/100 | Phase 1 |
| `storage/tessera_store.py` | 97/100 | 100/100 | Phase 1 |
| `storage/state.py` | 100/100 | 100/100 | Done |
| `storage/gc.py` | 100/100 | 100/100 | Done |
| `swarm/registry.py` | 100/100 | 100/100 | Done |
| `swarm/connector.py` | 100/100 | 100/100 | Done |
| `swarm/capacity.py` | 100/100 | 100/100 | Done |
| `swarm/partition.py` | 100/100 | 100/100 | Done |
| `transfer/scheduler.py` | 100/100 | 100/100 | Done |
| `transfer/scorer.py` | 100/100 | 100/100 | Done |
| `transfer/pipeline.py` | 100/100 | 100/100 | Done |
| `transfer/endgame.py` | 100/100 | 100/100 | Done |
| `transfer/assembler.py` | 100/100 | 100/100 | Done |
| `transfer/verifier.py` | 100/100 | 100/100 | Done |
| `wire/messages.py` | 100/100 | 100/100 | Done |
| `wire/state_machine.py` | 100/100 | 100/100 | Done |
| `wire/errors.py` | 100/100 | 100/100 | Done |

---

## Test Categories & Counts

| Category | Files | Tests | Purpose |
|----------|-------|-------|---------|
| Unit | 17 | 239 | Isolated module logic |
| Integration | 14 | 227 | Component interaction, storage I/O |
| Adversarial | 12 | 58 | Malicious input, crash recovery |
| AI Bridge | 7 | 98 | Intelligence adapters, sanitization |
| E2E | 5 | 55 | Full publish/fetch lifecycle |
| CLI | 2 | 94 | Command-line interface |
| Benchmarks | 8 | 8 | Performance baselines |
| **Total** | **65** | **730+** | |

---

## CI Coverage Gate

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=tessera --cov-branch --cov-fail-under=99"
```

This prevents merging any PR that drops below 99% combined line+branch coverage.

---

## Execution Order

1. **Phase 1** — Write failure recovery tests (6 lines, highest value)
2. **Phase 2** — httpx ImportError test or pragma (1 line)
3. **Phase 3** — `__main__` subprocess test or pragma (3 lines)
4. **Phase 4** — Hunt and close the 1 partial branch

After all phases: **100% line coverage, 100% branch coverage, 0 partial branches.**
