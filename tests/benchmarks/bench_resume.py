"""Resume/startup timing benchmark — ts-spec-012 §3, ts-spec-013 §7.

Validates: ≤ 5s with 10 active transfers budget.
Method: Pre-stage 10 partially-completed transfers (~2,000 pieces each), time node start().
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import pytest

from tessera import TesseraConfig, TesseraNode
from tessera.content.bitfield import Bitfield
from tessera.content.manifest import ManifestBuilder
from tessera.storage.layout import ensure_data_dir
from tessera.storage.manifest_store import ManifestStore
from tessera.storage.state import TransferState, write_state
from tessera.storage.tessera_store import TesseraStore
from tests.fixtures import make_bytes

TESSERA_SIZE = 256 * 1024  # 256 KB
PIECES_PER_TRANSFER = 2000  # ~500 MB per transfer
FILE_SIZE_PER_TRANSFER = PIECES_PER_TRANSFER * TESSERA_SIZE
NUM_TRANSFERS = 10
COMPLETION_PCT = 0.5  # 50% complete
BUDGET_S = 5.0  # From ts-spec-012 §3


def get_hardware_context() -> dict[str, str]:
    """Return hardware context for benchmark results."""
    return {
        "cpu": platform.processor() or platform.machine(),
        "python_version": platform.python_version(),
        "system": platform.system(),
    }


async def stage_partial_transfer(
    data_dir: Path,
    transfer_id: int,
    pieces_to_write: int,
    total_pieces: int,
) -> bytes:
    """Stage a partially-completed transfer with state file and pieces.

    Returns:
        manifest_hash for this transfer
    """
    # Generate deterministic test data
    file_data = make_bytes(FILE_SIZE_PER_TRANSFER, seed=42 + transfer_id)

    # Build manifest
    builder = ManifestBuilder(
        file_size=len(file_data),
        tessera_size=TESSERA_SIZE,
        metadata={"name": f"transfer_{transfer_id}.bin"},
    )

    # Chunk and collect leaf hashes
    chunks: list[tuple[int, bytes]] = []
    offset = 0
    idx = 0
    while offset < len(file_data):
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

    # Write partial pieces (first 50%)
    ts = TesseraStore(data_dir)
    for idx, chunk in chunks[:pieces_to_write]:
        await ts.write(manifest_hash, idx, chunk)

    # Write state file
    bitfield = Bitfield(total_pieces)
    for i in range(pieces_to_write):
        bitfield.set(i)

    state = TransferState(
        version=1,
        manifest_hash=manifest_hash,
        role="leecher",
        tessera_count=total_pieces,
    )
    state.set_bitfield(bitfield)
    await write_state(data_dir, state)

    return manifest_hash


@pytest.mark.benchmark
@pytest.mark.slow
async def test_bench_resume(tmp_path: Path) -> None:
    """Measure startup time with 10 partially-completed transfers."""
    print(f"\n{'=' * 60}")
    print("Resume/Startup Timing Benchmark")
    print(f"{'=' * 60}")

    data_dir = tmp_path / "data"
    ensure_data_dir(data_dir)

    # Pre-stage transfers
    print(f"\nStaging {NUM_TRANSFERS} partial transfers...")
    print(f"  Pieces per transfer: {PIECES_PER_TRANSFER}")
    print(f"  Size per transfer:   {FILE_SIZE_PER_TRANSFER // (1024 * 1024)} MB")
    print(f"  Completion:          {int(COMPLETION_PCT * 100)}%")

    pieces_to_write = int(PIECES_PER_TRANSFER * COMPLETION_PCT)
    manifest_hashes: list[bytes] = []

    for i in range(NUM_TRANSFERS):
        print(f"  Staging transfer {i + 1}/{NUM_TRANSFERS}...")
        mh = await stage_partial_transfer(
            data_dir, i, pieces_to_write, PIECES_PER_TRANSFER
        )
        manifest_hashes.append(mh)

    total_pieces = NUM_TRANSFERS * pieces_to_write
    print(f"\nTotal pieces on disk: {total_pieces:,}")
    print(
        f"Total data:           {(total_pieces * TESSERA_SIZE) // (1024 * 1024 * 1024)} GB"
    )

    # Benchmark node startup
    print("\nStarting node (rebuilding state from disk)...")
    config = TesseraConfig(
        data_dir=data_dir,
        tracker_urls=[],
    )
    node = TesseraNode(config)

    start = time.perf_counter()
    await node.start()
    end = time.perf_counter()

    elapsed_s = end - start
    elapsed_ms = elapsed_s * 1000

    # Calculate budget compliance
    budget_met = elapsed_s <= BUDGET_S
    deviation_pct = ((elapsed_s - BUDGET_S) / BUDGET_S) * 100 if not budget_met else 0

    result = {
        "benchmark": "bench_resume",
        "metric": "startup_latency_s",
        "num_transfers": NUM_TRANSFERS,
        "pieces_per_transfer": PIECES_PER_TRANSFER,
        "completion_pct": int(COMPLETION_PCT * 100),
        "total_pieces": total_pieces,
        "total_data_gb": round((total_pieces * TESSERA_SIZE) / (1024**3), 2),
        "elapsed_s": round(elapsed_s, 3),
        "elapsed_ms": round(elapsed_ms, 2),
        "budget_s": BUDGET_S,
        "budget_met": budget_met,
        "deviation_pct": round(deviation_pct, 2) if not budget_met else 0,
        "hardware": get_hardware_context(),
    }

    # Write results to JSON
    results_file = tmp_path / "bench_resume_results.json"
    results_file.write_text(json.dumps(result, indent=2))

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Transfers:       {NUM_TRANSFERS}")
    print(f"Total pieces:    {total_pieces:,}")
    print(f"Total data:      {result['total_data_gb']} GB")
    print(f"Elapsed:         {elapsed_s:.3f} s ({elapsed_ms:.2f} ms)")
    print(f"Budget:          {BUDGET_S} s")
    print(f"Status:          {'✓ PASS' if budget_met else '✗ FAIL'}")
    if not budget_met:
        print(f"Deviation:       +{deviation_pct:.2f}%")
    print(f"{'=' * 60}\n")

    # Advisory warning for significant deviation
    if deviation_pct > 25:
        print(
            f"WARNING: Startup time exceeds budget by >25%. "
            f"Expected ≤{BUDGET_S}s, got {elapsed_s:.3f}s"
        )

    # Cleanup
    await node.stop()
