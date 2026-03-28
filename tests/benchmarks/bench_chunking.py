"""Chunking throughput benchmark — ts-spec-012 §3, ts-spec-013 §7.

Validates: ≤ 1s/GB budget.
Method: Chunk files of 1 MB, 100 MB, 1 GB. Measure wall-clock time, report MB/s.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import pytest

from tessera.content.chunker import Chunker
from tests.fixtures import make_bytes

TESSERA_SIZE = 256 * 1024  # 256 KB
BUDGET_SECONDS_PER_GB = 1.0  # From ts-spec-012 §3

# Test file sizes
SIZE_1MB = 1 * 1024 * 1024
SIZE_100MB = 100 * 1024 * 1024
SIZE_1GB = 1024 * 1024 * 1024


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


def benchmark_chunking_single(file_path: Path, file_size: int) -> dict[str, float]:
    """Benchmark chunking a single file."""
    chunker = Chunker(tessera_size=TESSERA_SIZE)

    start = time.perf_counter()
    chunk_count = 0
    bytes_hashed = 0

    for _idx, chunk_data, _leaf_hash in chunker.chunk(file_path):
        chunk_count += 1
        bytes_hashed += len(chunk_data)

    end = time.perf_counter()

    elapsed_s = end - start
    throughput_mbps = (file_size / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0

    return {
        "elapsed_s": elapsed_s,
        "throughput_mbps": throughput_mbps,
        "chunk_count": chunk_count,
        "bytes_processed": bytes_hashed,
    }


@pytest.mark.benchmark
@pytest.mark.slow
def test_bench_chunking(tmp_path: Path) -> None:
    """Measure chunking throughput for 1 MB, 100 MB, and 1 GB files."""
    results = []

    test_files = [
        ("1MB", SIZE_1MB),
        ("100MB", SIZE_100MB),
        ("1GB", SIZE_1GB),
    ]

    print(f"\n{'=' * 60}")
    print("Chunking Throughput Benchmark")
    print(f"{'=' * 60}")

    for name, size in test_files:
        print(f"\nPreparing {name} test file...")

        # Create test file
        test_file = tmp_path / f"test_{name}.bin"
        test_file.write_bytes(make_bytes(size))

        print(f"Chunking {name} ({size:,} bytes)...")
        bench_result = benchmark_chunking_single(test_file, size)

        # Calculate budget compliance
        size_gb = size / (1024 * 1024 * 1024)
        budget_s = size_gb * BUDGET_SECONDS_PER_GB
        budget_met = bench_result["elapsed_s"] <= budget_s
        deviation_pct = (
            ((bench_result["elapsed_s"] - budget_s) / budget_s) * 100
            if not budget_met
            else 0
        )

        result = {
            "file_size": name,
            "file_size_bytes": size,
            "elapsed_s": round(bench_result["elapsed_s"], 3),
            "throughput_mbps": round(bench_result["throughput_mbps"], 2),
            "chunk_count": bench_result["chunk_count"],
            "budget_s": round(budget_s, 3),
            "budget_met": budget_met,
            "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        }
        results.append(result)

        # Print result
        print(f"  Elapsed:     {result['elapsed_s']:.3f} s")
        print(f"  Throughput:  {result['throughput_mbps']:.2f} MB/s")
        print(f"  Chunks:      {result['chunk_count']}")
        print(f"  Budget:      {result['budget_s']:.3f} s")
        print(f"  Status:      {'✓ PASS' if budget_met else '✗ FAIL'}")
        if not budget_met:
            print(f"  Deviation:   +{deviation_pct:.2f}%")

        # Clean up test file to free space
        test_file.unlink()

    # Aggregate results
    aggregate = {
        "benchmark": "bench_chunking",
        "metric": "chunking_throughput_mbps",
        "tessera_size_kb": TESSERA_SIZE // 1024,
        "budget_s_per_gb": BUDGET_SECONDS_PER_GB,
        "results": results,
        "hardware": get_hardware_context(),
    }

    # Write results to JSON
    results_file = tmp_path / "bench_chunking_results.json"
    results_file.write_text(json.dumps(aggregate, indent=2))

    print(f"\n{'=' * 60}")
    print(
        f"Summary: {sum(1 for r in results if r['budget_met'])}/{len(results)} passed"
    )
    print(f"{'=' * 60}\n")

    # Advisory warnings for significant deviations
    for result in results:
        if result["deviation_pct"] > 25:
            print(
                f"WARNING: {result['file_size']} chunking exceeds budget by >25%. "
                f"Expected ≤{result['budget_s']}s, got {result['elapsed_s']:.3f}s"
            )
