"""Publish latency benchmark — ts-spec-012 §3, ts-spec-013 §7.

Validates: ≤ 600 ms for 100 MB budget (excluding moderation and discovery).
Method: Time from publish() call to seeding-ready state (when it returns).
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tests.fixtures import make_bytes

SIZE_100MB = 100 * 1024 * 1024
BUDGET_MS_100MB = 600  # From ts-spec-012 §3


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


@pytest.mark.benchmark
@pytest.mark.slow
async def test_bench_publish_latency(tmp_path: Path) -> None:
    """Measure publish latency for 100 MB file."""
    print(f"\n{'=' * 60}")
    print("Publish Latency Benchmark")
    print(f"{'=' * 60}")

    # Create test file
    file_size = SIZE_100MB
    print(f"\nGenerating {file_size // (1024 * 1024)} MB test file...")
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(make_bytes(file_size))

    # Initialize node
    print("Initializing node...")
    config = TesseraConfig(
        data_dir=tmp_path / "data",
        tracker_urls=[],  # No discovery to isolate publish performance
    )
    node = TesseraNode(config)
    await node.start()

    # Benchmark publish
    print(f"Publishing {file_size // (1024 * 1024)} MB file...")
    start = time.perf_counter()
    manifest_hash = await node.publish(
        test_file,
        metadata={"description": "benchmark"},
        skip_moderation=True,  # Exclude moderation from benchmark
    )
    end = time.perf_counter()

    elapsed_ms = (end - start) * 1000
    elapsed_s = end - start

    # Calculate budget compliance
    budget_met = elapsed_ms <= BUDGET_MS_100MB
    deviation_pct = (
        ((elapsed_ms - BUDGET_MS_100MB) / BUDGET_MS_100MB) * 100
        if not budget_met
        else 0
    )

    # Calculate throughput (MB/s of chunking+hashing+writing)
    throughput_mbps = (file_size / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0

    result = {
        "benchmark": "bench_publish_latency",
        "metric": "publish_latency_ms",
        "file_size_mb": file_size // (1024 * 1024),
        "file_size_bytes": file_size,
        "elapsed_ms": round(elapsed_ms, 2),
        "elapsed_s": round(elapsed_s, 3),
        "throughput_mbps": round(throughput_mbps, 2),
        "manifest_hash": manifest_hash.hex(),
        "budget_ms": BUDGET_MS_100MB,
        "budget_met": budget_met,
        "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        "hardware": get_hardware_context(),
    }

    # Write results to JSON
    results_file = tmp_path / "bench_publish_latency_results.json"
    results_file.write_text(json.dumps(result, indent=2))

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"File size:       {file_size // (1024 * 1024)} MB")
    print(f"Elapsed:         {elapsed_ms:.2f} ms ({elapsed_s:.3f} s)")
    print(f"Throughput:      {throughput_mbps:.2f} MB/s")
    print(f"Manifest hash:   {manifest_hash.hex()[:16]}...")
    print(f"Budget:          {BUDGET_MS_100MB} ms")
    print(f"Status:          {'✓ PASS' if budget_met else '✗ FAIL'}")
    if not budget_met:
        print(f"Deviation:       +{deviation_pct:.2f}%")
    print(f"{'=' * 60}\n")

    # Advisory warning for significant deviation
    if deviation_pct > 25:
        print(
            f"WARNING: Publish latency exceeds budget by >25%. "
            f"Expected ≤{BUDGET_MS_100MB}ms, got {elapsed_ms:.2f}ms"
        )

    # Cleanup
    await node.stop()
