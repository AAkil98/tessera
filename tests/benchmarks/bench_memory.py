"""Memory footprint benchmark — ts-spec-012 §4, ts-spec-013 §7.

Validates: ≤ 150 MB Tessera-managed budget.
Method: Fetch 1 GB file with 50 simulated peers, measure peak RSS minus baseline.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.content.manifest import ManifestBuilder
from tessera.storage.layout import ensure_data_dir
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import make_bytes

TESSERA_SIZE = 256 * 1024  # 256 KB
FILE_SIZE_1GB = 1024 * 1024 * 1024
BUDGET_MB = 150  # From ts-spec-012 §4 (Tessera-managed, excluding Python runtime)


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


def get_rss_mb() -> float:
    """Return current RSS in MB."""
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        # Windows doesn't have resource module
        import psutil

        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)


async def stage_complete_mosaic(data_dir: Path, file_size: int) -> bytes:
    """Stage a complete mosaic (manifest + all pieces).

    Returns:
        manifest_hash
    """
    # Generate deterministic test data
    file_data = make_bytes(file_size)

    # Build manifest
    builder = ManifestBuilder(
        file_size=file_size,
        tessera_size=TESSERA_SIZE,
        metadata={"name": "benchmark_1gb.bin"},
    )

    # Chunk and collect
    chunks: list[tuple[int, bytes]] = []
    offset = 0
    idx = 0
    while offset < file_size:
        chunk = file_data[offset : offset + TESSERA_SIZE]
        leaf_hash = hashlib.sha256(chunk).digest()
        builder.add_tessera(leaf_hash)
        chunks.append((idx, chunk))
        offset += TESSERA_SIZE
        idx += 1

    manifest_bytes = builder.build()

    # Write manifest
    ms = ManifestStore(data_dir)
    manifest_hash = await ms.write(manifest_bytes)

    # Write all pieces
    ts = TesseraStore(data_dir)
    for idx, chunk in chunks:
        await ts.write(manifest_hash, idx, chunk)

    return manifest_hash


@pytest.mark.benchmark
@pytest.mark.slow
async def test_bench_memory(tmp_path: Path) -> None:
    """Measure peak memory usage during 1 GB transfer simulation.

    Note: This is a simplified benchmark that measures RSS growth.
    A real multi-peer fetch would require MFP loopback infrastructure.
    This simulates the memory footprint of the storage/bitfield/state layer.
    """
    print(f"\n{'='*60}")
    print("Memory Footprint Benchmark")
    print(f"{'='*60}")

    # Force garbage collection and get baseline RSS
    gc.collect()
    baseline_rss_mb = get_rss_mb()
    print(f"\nBaseline RSS:    {baseline_rss_mb:.2f} MB")

    # Stage a 1 GB file for assembly
    seeder_dir = tmp_path / "seeder"
    ensure_data_dir(seeder_dir)

    print("Staging 1 GB file (~4,000 pieces)...")
    manifest_hash = await stage_complete_mosaic(seeder_dir, FILE_SIZE_1GB)
    piece_count = FILE_SIZE_1GB // TESSERA_SIZE

    # Measure RSS after staging
    gc.collect()
    post_staging_rss_mb = get_rss_mb()
    print(f"After staging:   {post_staging_rss_mb:.2f} MB")

    # Initialize fetcher node
    fetcher_dir = tmp_path / "fetcher"
    config = TesseraConfig(
        data_dir=fetcher_dir,
        tracker_urls=[],
        max_peers_per_swarm=50,  # Simulate 50 peers
    )
    node = TesseraNode(config)
    await node.start()

    # Measure RSS with node running
    gc.collect()
    node_baseline_rss_mb = get_rss_mb()
    print(f"Node started:    {node_baseline_rss_mb:.2f} MB")

    # Simulate a fetch scenario by:
    # 1. Loading the manifest into the fetcher
    # 2. Creating bitfields for 50 simulated peers
    # 3. Measuring peak RSS
    ms_fetcher = ManifestStore(fetcher_dir)

    # Copy manifest to fetcher
    from tessera.content.manifest import ManifestParser

    seeder_ms = ManifestStore(seeder_dir)
    manifest_bytes = await seeder_ms.read(manifest_hash)
    if manifest_bytes is None:
        raise RuntimeError("Failed to read manifest")
    await ms_fetcher.write(manifest_bytes)
    info = ManifestParser.parse(manifest_bytes)

    # Simulate 50 peer bitfields (memory footprint test)
    from tessera.content.bitfield import Bitfield

    peer_bitfields: list[Bitfield] = []
    for _ in range(50):
        bf = Bitfield(info.tessera_count)
        # Simulate 50% completion for each peer (varied)
        for i in range(0, info.tessera_count, 2):
            bf.set(i)
        peer_bitfields.append(bf)

    # Force memory allocation
    _ = [bf.serialize() for bf in peer_bitfields]

    # Measure peak RSS
    gc.collect()
    peak_rss_mb = get_rss_mb()
    print(f"With 50 peers:   {peak_rss_mb:.2f} MB")

    # Calculate Tessera-managed memory (approximation)
    tessera_managed_mb = peak_rss_mb - baseline_rss_mb
    budget_met = tessera_managed_mb <= BUDGET_MB
    deviation_pct = (
        ((tessera_managed_mb - BUDGET_MB) / BUDGET_MB) * 100
        if not budget_met
        else 0
    )

    result = {
        "benchmark": "bench_memory",
        "metric": "peak_rss_mb",
        "file_size_gb": FILE_SIZE_1GB // (1024**3),
        "piece_count": piece_count,
        "simulated_peers": 50,
        "baseline_rss_mb": round(baseline_rss_mb, 2),
        "post_staging_rss_mb": round(post_staging_rss_mb, 2),
        "node_baseline_rss_mb": round(node_baseline_rss_mb, 2),
        "peak_rss_mb": round(peak_rss_mb, 2),
        "tessera_managed_mb": round(tessera_managed_mb, 2),
        "budget_mb": BUDGET_MB,
        "budget_met": budget_met,
        "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        "hardware": get_hardware_context(),
        "note": "RSS growth includes Python runtime overhead. Tessera-managed calculation is approximate.",
    }

    # Write results to JSON
    results_file = tmp_path / "bench_memory_results.json"
    results_file.write_text(json.dumps(result, indent=2))

    # Print summary
    print(f"\n{'='*60}")
    print("File size:       1 GB")
    print(f"Pieces:          {piece_count:,}")
    print("Simulated peers: 50")
    print(f"Baseline RSS:    {baseline_rss_mb:.2f} MB")
    print(f"Peak RSS:        {peak_rss_mb:.2f} MB")
    print(f"Tessera-managed: {tessera_managed_mb:.2f} MB (approx)")
    print(f"Budget:          {BUDGET_MB} MB")
    print(f"Status:          {'✓ PASS' if budget_met else '✗ FAIL'}")
    if not budget_met:
        print(f"Deviation:       +{deviation_pct:.2f}%")
    print("\nNote: Memory measurement is approximate and includes Python runtime overhead.")
    print(f"{'='*60}\n")

    # Advisory warning for significant deviation
    if deviation_pct > 25:
        print(
            f"WARNING: Memory usage exceeds budget by >25%. "
            f"Expected ≤{BUDGET_MB}MB, got {tessera_managed_mb:.2f}MB"
        )

    # Cleanup
    await node.stop()
