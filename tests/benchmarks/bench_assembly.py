"""Assembly throughput benchmark — ts-spec-012 §3, ts-spec-013 §7.

Validates: ≤ 500 ms for 100 MB budget.
Method: Pre-stage ~400 piece files, measure assembly time, report MB/s.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import pytest

from tessera.content.manifest import ManifestBuilder
from tessera.storage.layout import ensure_data_dir
from tessera.storage.tessera_store import TesseraStore
from tessera.types import ManifestInfo
from tests.fixtures import make_bytes

TESSERA_SIZE = 256 * 1024  # 256 KB
SIZE_100MB = 100 * 1024 * 1024
BUDGET_MS_100MB = 500  # From ts-spec-012 §3


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


async def stage_pieces(
    data_dir: Path, file_data: bytes, tessera_size: int
) -> tuple[bytes, ManifestInfo]:
    """Pre-stage piece files for benchmarking assembly.

    Returns:
        (manifest_hash, manifest_info)
    """
    ensure_data_dir(data_dir)
    ts = TesseraStore(data_dir)

    # Build manifest
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=tessera_size,
        metadata={"name": "benchmark.bin"},
    )

    # Chunk and write pieces
    offset = 0
    idx = 0
    while offset < len(file_data):
        chunk = file_data[offset : offset + tessera_size]
        leaf_hash = hashlib.sha256(chunk).digest()
        builder.add_tessera(leaf_hash)
        await ts.write(hashlib.sha256(b"fake_manifest").digest(), idx, chunk)
        offset += tessera_size
        idx += 1

    manifest_bytes = builder.build()
    manifest_hash = hashlib.sha256(manifest_bytes).digest()

    # Re-write pieces with correct manifest hash
    offset = 0
    idx = 0
    while offset < len(file_data):
        chunk = file_data[offset : offset + tessera_size]
        await ts.write(manifest_hash, idx, chunk)
        offset += tessera_size
        idx += 1

    # Parse manifest to get ManifestInfo
    from tessera.content.manifest import ManifestParser

    manifest_info = ManifestParser.parse(manifest_bytes)

    return manifest_hash, manifest_info


@pytest.mark.benchmark
@pytest.mark.slow
async def test_bench_assembly(tmp_path: Path) -> None:
    """Measure assembly throughput for 100 MB file (~400 pieces)."""
    print(f"\n{'='*60}")
    print("Assembly Throughput Benchmark")
    print(f"{'='*60}")

    # Generate test data
    file_size = SIZE_100MB
    print(f"\nGenerating {file_size // (1024*1024)} MB test data...")
    test_data = make_bytes(file_size)

    # Pre-stage pieces
    print("Staging pieces to disk...")
    manifest_hash, manifest_info = await stage_pieces(
        tmp_path, test_data, TESSERA_SIZE
    )
    piece_count = manifest_info.tessera_count
    print(f"Staged {piece_count} pieces ({piece_count * TESSERA_SIZE // (1024*1024)} MB)")

    # Benchmark assembly
    output_path = tmp_path / "assembled.bin"
    ts = TesseraStore(tmp_path)

    print("Assembling...")
    start = time.perf_counter()
    await ts.assemble(manifest_hash, manifest_info, output_path)
    end = time.perf_counter()

    elapsed_ms = (end - start) * 1000
    elapsed_s = end - start
    throughput_mbps = (file_size / (1024 * 1024)) / elapsed_s if elapsed_s > 0 else 0

    # Verify correctness
    assembled_data = output_path.read_bytes()
    assert len(assembled_data) == len(test_data), "Size mismatch after assembly"
    assert assembled_data == test_data, "Data mismatch after assembly"

    # Calculate budget compliance
    budget_met = elapsed_ms <= BUDGET_MS_100MB
    deviation_pct = (
        ((elapsed_ms - BUDGET_MS_100MB) / BUDGET_MS_100MB) * 100
        if not budget_met
        else 0
    )

    result = {
        "benchmark": "bench_assembly",
        "metric": "assembly_throughput_mbps",
        "file_size_mb": file_size // (1024 * 1024),
        "file_size_bytes": file_size,
        "piece_count": piece_count,
        "tessera_size_kb": TESSERA_SIZE // 1024,
        "elapsed_ms": round(elapsed_ms, 2),
        "elapsed_s": round(elapsed_s, 3),
        "throughput_mbps": round(throughput_mbps, 2),
        "budget_ms": BUDGET_MS_100MB,
        "budget_met": budget_met,
        "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        "hardware": get_hardware_context(),
    }

    # Write results to JSON
    results_file = tmp_path / "bench_assembly_results.json"
    results_file.write_text(json.dumps(result, indent=2))

    # Print summary
    print(f"\n{'='*60}")
    print(f"File size:       {file_size // (1024*1024)} MB")
    print(f"Piece count:     {piece_count}")
    print(f"Elapsed:         {elapsed_ms:.2f} ms ({elapsed_s:.3f} s)")
    print(f"Throughput:      {throughput_mbps:.2f} MB/s")
    print(f"Budget:          {BUDGET_MS_100MB} ms")
    print(f"Status:          {'✓ PASS' if budget_met else '✗ FAIL'}")
    if not budget_met:
        print(f"Deviation:       +{deviation_pct:.2f}%")
    print(f"{'='*60}\n")

    # Advisory warning for significant deviation
    if deviation_pct > 25:
        print(
            f"WARNING: Assembly time exceeds budget by >25%. "
            f"Expected ≤{BUDGET_MS_100MB}ms, got {elapsed_ms:.2f}ms"
        )
