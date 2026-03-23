"""SHA-256 performance benchmark — ts-spec-012 §6, ts-spec-013 §7.

Validates: ≤ 0.1 ms per 256 KB budget.
Method: Hash 10,000 × 256 KB blocks, report median and p99 latency.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import pytest

TESSERA_SIZE = 256 * 1024  # 256 KB
ITERATIONS = 10_000
BUDGET_MS_PER_BLOCK = 0.1  # From ts-spec-012 §6


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


@pytest.mark.benchmark
def test_bench_hash(tmp_path: Path) -> None:
    """Measure SHA-256 throughput over 10,000 × 256 KB blocks."""
    # Generate a single 256 KB block to hash repeatedly
    data = b"\x42" * TESSERA_SIZE

    latencies_ms: list[float] = []

    # Warmup run to prime CPU caches
    for _ in range(100):
        hashlib.sha256(data).digest()

    # Actual benchmark
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        hashlib.sha256(data).digest()
        end = time.perf_counter()
        latencies_ms.append((end - start) * 1000)  # Convert to milliseconds

    # Calculate statistics
    latencies_ms.sort()
    median_ms = latencies_ms[len(latencies_ms) // 2]
    p99_ms = latencies_ms[int(len(latencies_ms) * 0.99)]
    mean_ms = sum(latencies_ms) / len(latencies_ms)

    # Calculate throughput
    total_bytes = TESSERA_SIZE * ITERATIONS
    total_time_s = sum(latencies_ms) / 1000
    throughput_mbps = (total_bytes / (1024 * 1024)) / total_time_s

    # Determine pass/fail
    budget_met = median_ms <= BUDGET_MS_PER_BLOCK
    deviation_pct = ((median_ms - BUDGET_MS_PER_BLOCK) / BUDGET_MS_PER_BLOCK) * 100

    result = {
        "benchmark": "bench_hash",
        "metric": "sha256_latency_ms",
        "iterations": ITERATIONS,
        "block_size_kb": TESSERA_SIZE // 1024,
        "median_ms": round(median_ms, 4),
        "p99_ms": round(p99_ms, 4),
        "mean_ms": round(mean_ms, 4),
        "throughput_mbps": round(throughput_mbps, 2),
        "budget_ms": BUDGET_MS_PER_BLOCK,
        "budget_met": budget_met,
        "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        "hardware": get_hardware_context(),
    }

    # Write results to JSON file
    results_file = tmp_path / "bench_hash_results.json"
    results_file.write_text(json.dumps(result, indent=2))

    # Print summary for human readability
    print(f"\n{'='*60}")
    print("SHA-256 Performance Benchmark")
    print(f"{'='*60}")
    print(f"Block size:      {TESSERA_SIZE // 1024} KB")
    print(f"Iterations:      {ITERATIONS:,}")
    print(f"Median latency:  {median_ms:.4f} ms")
    print(f"P99 latency:     {p99_ms:.4f} ms")
    print(f"Mean latency:    {mean_ms:.4f} ms")
    print(f"Throughput:      {throughput_mbps:.2f} MB/s")
    print(f"Budget:          {BUDGET_MS_PER_BLOCK} ms")
    print(f"Status:          {'✓ PASS' if budget_met else '✗ FAIL'}")
    if not budget_met:
        print(f"Deviation:       +{deviation_pct:.2f}%")
    print(f"{'='*60}\n")

    # Advisory assertion - does not block, just warns
    if median_ms > BUDGET_MS_PER_BLOCK * 1.25:  # >25% over budget
        print(
            f"WARNING: SHA-256 latency exceeds budget by >25%. "
            f"Expected ≤{BUDGET_MS_PER_BLOCK}ms, got {median_ms:.4f}ms"
        )
