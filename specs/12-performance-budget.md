# Performance Budget

```yaml
id: ts-spec-012
type: spec
status: draft
created: 2026-03-18
revised: 2026-03-18
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [performance, budget, benchmarks, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Transfer Throughput
3. Latency Targets
4. Memory Budget
5. Disk I/O Budget
6. CPU Budget
7. Scalability Limits
8. Measurement & Reporting
9. References

## 1. Purpose & Scope

This document defines the quantitative performance targets that the Tessera implementation must meet. It translates the qualitative goals from ts-spec-001 into measurable budgets — how fast transfers should be, how much memory and CPU the node may consume, and where the system is expected to hit its limits.

### What this spec defines

- **Transfer throughput.** Target bytes-per-second for single-mosaic and multi-mosaic transfers, and the overhead Tessera adds relative to raw MFP channel throughput.
- **Latency targets.** Time-to-first-byte, publish latency (file to seeding), and API call response times.
- **Memory budget.** Per-swarm and per-node memory ceilings for in-memory state — bitfields, peer tables, scoring data, manifest index.
- **Disk I/O budget.** Write amplification from the temp-then-rename pattern, sequential vs random I/O expectations, and assembly throughput.
- **CPU budget.** Hashing costs (SHA-256 per tessera and whole-file), serialization overhead, and the impact of AI adapter calls.
- **Scalability limits.** The capacity envelope — maximum file size, maximum concurrent swarms, maximum peers per swarm — and how performance degrades as these limits are approached.
- **Measurement & reporting.** How performance is observed at runtime and how benchmarks are structured during development.

### What this spec does not define

| Concern | Owner |
|---------|-------|
| MFP channel throughput and encryption overhead | MFP documentation |
| madakit LLM call latency | madakit documentation |
| Network bandwidth between peers | Deployment environment |
| Disk hardware performance | Deployment environment |

### Design principles

- **Budget, not benchmark.** These are targets the implementation must stay within, not measurements of a running system. They guide design trade-offs — if a feature would exceed a budget, it must be redesigned or made optional.
- **Bottleneck-aware.** Tessera sits on top of MFP (encryption, transport) and the filesystem (reads, writes). The performance budget accounts for these layers — Tessera's overhead is defined as the gap between raw MFP throughput and observed transfer speed.
- **Target scale.** All budgets are set for the declared operating envelope: tens to hundreds of peers (NG3, ts-spec-001), up to 10 concurrent swarms (ts-spec-007), files up to tens of gigabytes.

---

## 2. Transfer Throughput

Transfer throughput is the primary performance metric. Tessera must deliver files at a rate that justifies the complexity of swarm-based transfer over a simple point-to-point copy.

### Single-peer throughput

When fetching from a single seeder, Tessera adds overhead on top of raw MFP channel throughput. The budget for that overhead:

| Metric | Budget | Rationale |
|--------|--------|-----------|
| Tessera overhead | ≤ 15% | SHA-256 hashing, bitfield updates, piece selection logic, temp-then-rename writes. A raw MFP channel delivering 100 MB/s should yield ≥ 85 MB/s at the Tessera layer. |
| Pipeline saturation | ≥ 80% | With `max_requests_per_peer = 5`, the request pipeline should keep the MFP channel utilized at least 80% of the time. Gaps between piece completions and new requests must not starve the channel. |

### Multi-peer throughput

The value of swarm-based transfer is parallelism. Throughput should scale with the number of peers contributing unique pieces.

| Peers | Expected throughput | Notes |
|-------|-------------------|-------|
| 1 | ≥ 85% of single-peer MFP rate | Baseline. |
| 5 | ≥ 3.5× single-peer rate | Sub-linear due to piece selection overhead and peer coordination. |
| 10 | ≥ 6× single-peer rate | Diminishing returns from `max_requests_per_swarm = 20` ceiling. |
| 20+ | ≥ 8× single-peer rate | Concurrency limit dominates. Additional peers improve resilience, not throughput. |

These targets assume all peers have equivalent bandwidth. In heterogeneous swarms, throughput is bounded by the aggregate bandwidth of the top peers selected by the scoring algorithm (ts-spec-008).

### Overhead breakdown

The 15% overhead budget is allocated across components:

| Component | Budget | Source |
|-----------|--------|--------|
| SHA-256 hashing (per tessera) | ≤ 5% | 256 KB hash at ~2 GB/s on modern CPUs ≈ 0.1 ms per tessera. |
| Piece selection + bitfield | ≤ 2% | Rarest-first scan is O(n) over peers' bitfields. |
| Disk write (temp + rename) | ≤ 5% | Two syscalls per tessera. Amortized by OS page cache. |
| Protocol framing | ≤ 2% | 5-byte PIECE header per 256 KB payload ≈ 0.002% wire overhead. Serialization/deserialization cost. |
| Peer scoring update | ≤ 1% | EMA update per completed piece — O(1) arithmetic. |

### Throughput floor

Tessera must not perform worse than these absolute minimums regardless of deployment environment:

| Scenario | Floor |
|----------|-------|
| Single peer, LAN (1 Gbps) | ≥ 50 MB/s |
| Single peer, WAN (100 Mbps) | ≥ 10 MB/s (network-bound) |
| 10 peers, LAN | ≥ 200 MB/s |

If measured throughput falls below these floors, it indicates a bug or misconfiguration — not an expected operating condition.

---

## 3. Latency Targets

Latency targets define how quickly Tessera responds to user and agent actions. These are wall-clock times from API call to observable result.

### Publish latency

Time from `node.publish(file_path)` call to the node being ready to serve pieces to peers.

| Step | Budget | Notes |
|------|--------|-------|
| Chunking | ≤ 1s per GB | Sequential read + SHA-256 per tessera. Disk-read bound on HDD, CPU-bound on SSD. |
| Manifest construction | ≤ 10 ms | Merkle tree build is O(n) over leaf hashes. Manifest serialization is trivial. |
| Manifest write to disk | ≤ 1 ms | Single atomic write, small file. |
| Discovery announce | ≤ 500 ms | Network round-trip to tracker. Varies by backend. |
| Content moderation (if enabled) | ≤ 5s | LLM call via madakit. Not on the critical path — announce proceeds in parallel if moderation is async. |
| **Total (excluding moderation)** | **≤ 1.5s per GB + 500 ms** | A 100 MB file should be publishable in under 600 ms. |

### Fetch latency

#### Time to first byte

Time from `node.fetch(manifest_hash)` to receiving the first verified tessera.

| Step | Budget | Notes |
|------|--------|-------|
| Discovery lookup | ≤ 500 ms | Tracker query. |
| Peer connection (first peer) | ≤ 500 ms | MFP handshake + Tessera HANDSHAKE + BITFIELD exchange. |
| First piece request + delivery | ≤ request_timeout (30s) | Depends on peer responsiveness and network. Typical LAN: < 50 ms. |
| **Total (typical, LAN)** | **≤ 1.5s** | From API call to first tessera on disk. |

#### Assembly latency

Time from last tessera received to assembled file available on disk.

| File size | Budget | Notes |
|-----------|--------|-------|
| 100 MB | ≤ 500 ms | Sequential read of ~400 pieces + SHA-256 of assembled file. |
| 1 GB | ≤ 3s | Disk-read bound. ~4,000 pieces read sequentially. |
| 10 GB | ≤ 30s | Linear scaling. Sequential I/O at ≥ 300 MB/s. |

### API call response times

For non-transfer API calls — operations that query state but do not move data.

| Call | Budget | Notes |
|------|--------|-------|
| `status()` — single mosaic | ≤ 1 ms | In-memory lookup. |
| `status()` — all swarms | ≤ 5 ms | Iterate up to `max_swarms_per_node` (10) swarms. |
| `cancel()` | ≤ 10 ms | Swarm state transition + CANCEL messages to peers. Peer messages are fire-and-forget. |
| `query()` | ≤ 10s | Dominated by LLM call latency. The manifest index scan itself is < 5 ms. |

### Startup latency

Time for `TesseraNode.start()` to complete and be ready to accept API calls.

| Condition | Budget | Notes |
|-----------|--------|-------|
| Fresh node (empty data_dir) | ≤ 100 ms | Directory creation + MFP agent bind. |
| Resuming node (10 active transfers) | ≤ 5s | State file parsing + disk scan for bitfield rebuild + manifest index rebuild. Dominated by tessera verification I/O. |

---

## 4. Memory Budget

Tessera's in-memory footprint must remain bounded and predictable. Memory usage scales with the number of active swarms and peers, not with file size — file data flows through to disk, it is not held in memory.

### Per-swarm memory

| Component | Formula | Example (1 GB file, 50 peers) |
|-----------|---------|-------------------------------|
| Local bitfield | ⌈tessera_count / 8⌉ bytes | 4,000 bits = 500 B |
| Peer bitfields | peers × ⌈tessera_count / 8⌉ bytes | 50 × 500 B = 25 KB |
| Rarity table | tessera_count × 2 bytes (uint16 counts) | 4,000 × 2 = 8 KB |
| Peer scoring state | peers × ~200 bytes (4 metrics, EMA state, metadata) | 50 × 200 = 10 KB |
| Request pipeline state | max_requests_per_swarm × ~100 bytes (request objects) | 20 × 100 = 2 KB |
| Retry/stuck tracking | tessera_count × ~16 bytes (worst case, all retried) | 4,000 × 16 = 64 KB |
| Piece data in flight | max_requests_per_swarm × tessera_size | 20 × 256 KB = 5 MB |
| **Per-swarm total** | | **≈ 5.1 MB** |

Piece data in flight dominates. This is transient — each piece is written to disk and released as soon as it is verified.

### Per-node memory

| Component | Formula | Example (10 swarms, 200 manifests) |
|-----------|---------|-------------------------------------|
| All swarms | swarms × per-swarm cost | 10 × 5.1 MB = 51 MB |
| Manifest index | manifests × ~500 bytes (hash + metadata summary) | 200 × 500 B = 100 KB |
| MFP agent overhead | Fixed (MFP internals) | ~10 MB (estimated) |
| AI adapter state | AIStatus + cached hints | ≤ 1 MB |
| Event loop + Python runtime | Fixed | ~30 MB |
| **Per-node total** | | **≈ 92 MB** |

### Memory ceiling

| Scope | Budget |
|-------|--------|
| Per swarm (excluding in-flight pieces) | ≤ 512 KB |
| Per swarm (including in-flight pieces) | ≤ 10 MB |
| Per node (all swarms at capacity) | ≤ 150 MB |

These ceilings are exclusive of the Python runtime and MFP agent — they cover only Tessera-managed allocations. If a node approaches 150 MB of Tessera-managed memory, it should refuse new swarms via `CapacityError` rather than grow unbounded.

### What is NOT held in memory

- **File content.** Tesserae are read from disk on demand (serving to peers) and written to disk immediately on receipt. No piece data is cached in memory beyond the in-flight request pipeline.
- **Assembled files.** Assembly streams from tessera files to the output file. The Assembler reads one tessera at a time — peak memory during assembly is one `tessera_size` buffer (256 KB).
- **Manifest bodies.** Parsed manifest data (header, metadata, leaf hashes) is loaded on demand and released after use. Only the manifest index (hash → metadata summary) persists in memory.

---

## 5. Disk I/O Budget

Disk I/O is the most likely bottleneck on commodity hardware. The storage layer (ts-spec-011) uses a write-to-temp-then-rename pattern that doubles syscall count but guarantees crash safety. The budget accounts for this overhead.

### Write amplification

| Operation | Syscalls | Bytes written | Notes |
|-----------|----------|---------------|-------|
| Tessera write | 3 (open + write + rename) | 1× tessera_size | No amplification on data. The temp file and final file share the same data — rename is metadata-only. |
| State file write | 3 (open + write + rename) | ~2 KB | Infrequent (every 5% progress). Negligible I/O. |
| Manifest write | 3 (open + write + rename) | ~128 KB (1 GB file) | Once per mosaic. |

**Effective write amplification: 1.0×** on data bytes. The temp-then-rename pattern adds syscall overhead but does not duplicate data writes. The OS page cache absorbs the rename's directory entry update.

### Sequential vs random I/O

| Operation | Access pattern | Notes |
|-----------|---------------|-------|
| Chunking (publish) | Sequential read | Single pass over source file. Optimal for all disk types. |
| Tessera write (fetch) | Random write | Pieces arrive in rarest-first order, not sequential. Each write targets a different file. Mitigated by OS write coalescing. |
| Assembly | Sequential read | Tesserae read in index order (0, 1, 2, ...). Optimal. |
| Tessera read (serving) | Random read | Peers request arbitrary pieces. Unavoidable. SSD strongly preferred for seeders. |

### I/O throughput targets

| Operation | Budget | Assumption |
|-----------|--------|------------|
| Chunking throughput | ≥ 500 MB/s | SSD sequential read. HDD: ≥ 150 MB/s. |
| Tessera write throughput | ≥ 200 MB/s | SSD random write with OS page cache. HDD: ≥ 50 MB/s. |
| Assembly throughput | ≥ 300 MB/s | SSD sequential read of piece files. HDD: ≥ 100 MB/s. |
| Serving throughput (single peer) | ≥ 100 MB/s | SSD random read. Typically network-bound before disk-bound. |

### I/O concurrency

Disk operations run in the thread pool via `asyncio.to_thread()` (ADR-003). The thread pool absorbs bursts of concurrent piece writes without blocking the event loop.

| Scenario | Concurrent disk ops | Notes |
|----------|-------------------|-------|
| Single swarm, 20 in-flight requests | Up to 20 concurrent writes | Each completed piece triggers a write. Thread pool handles contention. |
| 10 swarms at capacity | Up to 200 concurrent writes | Theoretical maximum. In practice, not all requests complete simultaneously. Thread pool size (`min(32, cpu_count + 4)`) serializes excess. |

The thread pool acts as a natural throttle. When disk I/O is slower than network delivery, the thread pool queue grows, backpressuring the request pipeline via semaphore saturation (ts-spec-008). This prevents unbounded memory growth from buffered pieces.

### fsync policy

Tessera does **not** call `fsync()` after tessera writes. The rationale:

- Tesserae are content-addressable. A lost write is detected on resume (bitfield rebuild) and re-requested from peers. The cost of data loss is a re-download, not corruption.
- `fsync()` on every 256 KB write would reduce SSD write throughput by 10–50× due to forced flush.
- State files are also not fsynced — the write-to-temp-then-rename pattern guarantees atomicity (old or new, never partial), and stale state is corrected by disk scan on resume.

The only file that warrants `fsync()` is `node.id` on first creation, since it cannot be regenerated.

---

## 6. CPU Budget

Tessera's CPU usage is dominated by cryptographic hashing. All other computation — piece selection, peer scoring, protocol serialization — is negligible by comparison.

### Hashing costs

SHA-256 is the only hash algorithm used (ts-spec-006). Python's `hashlib.sha256` delegates to OpenSSL, which uses hardware acceleration (SHA-NI) on modern x86 CPUs.

| Operation | Data hashed | Frequency | Cost per unit | Notes |
|-----------|-------------|-----------|---------------|-------|
| Tessera hash (verify on receive) | 256 KB | Once per piece received | ~0.1 ms | Hardware-accelerated SHA-256 at ~2 GB/s. |
| Tessera hash (chunking on publish) | 256 KB | Once per piece chunked | ~0.1 ms | Same cost as verification. |
| Merkle tree construction | 32 bytes per node | Once per mosaic | < 1 ms (4,000 leaves) | Internal nodes hash two 32-byte children. Negligible. |
| Whole-file verification | Entire file | Once per completed fetch | ~0.5s per GB | Sequential hash of assembled file. |
| Manifest hash | Entire manifest | Once per manifest | < 0.1 ms | Manifests are small (~128 KB for 1 GB file). |
| Bitfield rebuild (resume) | 256 KB per tessera | Once per resume, per stored tessera | ~0.1 ms × tessera_count | 4,000 tesserae ≈ 400 ms. Dominates resume latency. |

### CPU budget by scenario

| Scenario | Hashing CPU time | Other CPU time | Total |
|----------|-----------------|----------------|-------|
| Publish 1 GB file | 500 ms (chunking) + 0.5 ms (Merkle) | < 10 ms | ~500 ms |
| Fetch 1 GB from 10 peers | 400 ms (verify 4,000 tesserae) + 500 ms (whole-file) | < 50 ms | ~950 ms |
| Serve 1 GB to 1 peer | 0 ms (no re-hashing on serve) | < 10 ms (protocol framing) | ~10 ms |
| Resume with 2,000 of 4,000 tesserae | 200 ms (re-verify 2,000 pieces) | < 5 ms | ~205 ms |

### Non-hashing CPU

| Component | Cost | Notes |
|-----------|------|-------|
| Piece selection (rarest-first) | O(tessera_count × peer_count) per selection | 4,000 × 50 = 200K comparisons. < 1 ms in Python. |
| Peer scoring update | O(1) per completed piece | 4 EMA updates + weighted sum. Microseconds. |
| Protocol serialization | O(message_size) per message | `struct.pack` / `struct.unpack`. < 0.01 ms per message. |
| Bitfield operations | O(tessera_count / 64) per operation | Bitwise operations on `int`. Sub-microsecond. |
| State file serialization (JSON) | O(state_size) per write | < 1 ms. Infrequent. |

### AI adapter CPU

AI adapter calls (ts-spec-009) are I/O-bound (waiting for LLM responses), not CPU-bound. The CPU cost is limited to:

| Operation | CPU cost | Frequency |
|-----------|----------|-----------|
| Metadata sanitization | < 1 ms | Before each LLM call. String operations on small metadata. |
| Manifest index scan | O(manifest_count) | Per `query()` call. Collecting metadata for LLM prompt. |
| Confidence blending | O(peer_count) | Per ranking update (every 60s). Arithmetic. |

AI adapter CPU is negligible relative to hashing. The LLM call latency (seconds) dwarfs local computation (microseconds).

### Thread pool sizing

The default thread pool (`min(32, os.cpu_count() + 4)`) is shared between disk I/O and CPU-heavy hashing. On a 4-core machine, the pool is 8 threads. This is sufficient because:

- Hashing runs at memory bandwidth, not CPU instruction throughput. One thread saturates one core's memory bus.
- Disk I/O threads spend most of their time blocked on syscalls, not consuming CPU.
- At peak (10 swarms, 20 requests each), at most 20 threads are active — within the pool's capacity on typical hardware.

If profiling reveals contention between hashing and disk I/O threads, a dedicated hash thread pool can be introduced without changing the architecture.

---

## 7. Scalability Limits

Tessera is designed for tens to hundreds of peers (NG3, ts-spec-001). This section defines the hard limits of the operating envelope and how performance degrades as those limits are approached.

### Capacity envelope

| Dimension | Hard limit | Source | Notes |
|-----------|-----------|--------|-------|
| Max peers per swarm | 50 | ts-spec-007 | Configurable via `max_peers_per_swarm`. |
| Max swarms per node | 10 | ts-spec-007 | Configurable via `max_swarms_per_node`. |
| Max concurrent requests per swarm | 20 | ts-spec-008 | Configurable via `max_requests_per_swarm`. |
| Max concurrent requests per peer | 5 | ts-spec-008 | Configurable via `max_requests_per_peer`. |
| Max tessera count per mosaic | 999,999 | ts-spec-011 | 6-digit file naming. ~244 GB at 256 KB. |
| Max metadata keys | 64 | ts-spec-010 | Per manifest. |
| Max metadata value size | 1,024 bytes | ts-spec-010 | Per key-value pair. |
| Max tessera size | MFP max_payload - 5 | ts-spec-005 | Default: 1 MB - 5 = 1,048,571 bytes. |

### File size scaling

| File size | Tesserae (256 KB) | Manifest size | Bitfield size | Merkle tree depth |
|-----------|-------------------|---------------|---------------|-------------------|
| 10 MB | 40 | ~2 KB | 5 bytes | 6 |
| 100 MB | 400 | ~14 KB | 50 bytes | 9 |
| 1 GB | 4,000 | ~130 KB | 500 bytes | 12 |
| 10 GB | 40,000 | ~1.3 MB | 5 KB | 16 |
| 100 GB | 400,000 | ~12.5 MB | 49 KB | 19 |

At 100 GB, the manifest exceeds 1 MB and requires chunked transfer (ts-spec-006, section 6). Bitfield exchange (BITFIELD message) grows to 49 KB — still well within a single MFP frame. Piece selection (rarest-first scan) over 400,000 tesserae with 50 peers is ~20M comparisons — potentially 10–50 ms in Python. This is the first scalability concern for very large files.

### Peer count scaling

| Peers | Per-swarm memory (bitfields) | Rarest-first scan cost | Scoring update cost |
|-------|------------------------------|----------------------|-------------------|
| 10 | 5 KB | < 0.5 ms | Negligible |
| 50 | 25 KB | < 1 ms | Negligible |
| 100 | 50 KB | ~2 ms | Negligible |
| 500 | 250 KB | ~10 ms | < 0.5 ms |

Beyond 50 peers, the primary cost is bitfield storage and rarest-first scan time. Peer scoring remains O(1) per update. At 500 peers (well beyond the target scale), memory and selection costs are still manageable, but MFP connection overhead (one bilateral channel per peer) becomes the practical bottleneck.

### Degradation behavior

When limits are approached, Tessera degrades predictably rather than failing catastrophically:

| Condition | Behavior |
|-----------|----------|
| `max_swarms_per_node` reached | New `publish()` / `fetch()` raises `CapacityError`. Existing swarms unaffected. |
| `max_peers_per_swarm` reached | New peer connections are rejected with REJECT (0x0301). Existing peers unaffected. |
| `max_requests_per_swarm` reached | New piece requests queue in the backlog (ts-spec-008). Throughput plateaus. No failure. |
| Very large file (>10 GB) | Piece selection latency increases. Transfer still completes. Assembly latency grows linearly. |
| Disk full | Swarm transitions to DRAINING (ts-spec-011, section 6). No corruption. Resumes when space is freed. |
| Thread pool exhaustion | Disk I/O and hashing queue behind existing work. Backpressure propagates to request pipeline via semaphores. Throughput drops but no data is lost. |

---

## 8. Measurement & Reporting

Performance budgets are only useful if they can be verified. This section defines how performance is observed at runtime and how benchmarks are structured during development.

### Runtime observability

Tessera exposes performance data through two mechanisms already defined in prior specs:

**TransferStatus** (ts-spec-008, section 7) provides per-mosaic metrics during active transfers:
- `throughput_bps` — 10-second sliding window, bytes per second.
- `pieces_done` / `pieces_total` — progress toward completion.
- `eta_seconds` — estimated time remaining.
- Per-peer throughput and latency in the peer detail list.

**AIStatus** (ts-spec-009) provides AI adapter performance:
- Call counts, failure counts, and average latency per adapter.

These are queryable via `TesseraNode.status()` (ts-spec-010) and the `tessera status` CLI command with `--json` for machine parsing.

### Logging

Performance-relevant events are logged at `debug` level to avoid noise in normal operation. Key log points:

| Event | Data logged |
|-------|-------------|
| Piece verified | Tessera index, hash time (ms), peer, total elapsed |
| State file written | Mosaic hash, progress %, file size |
| Assembly started/completed | Mosaic hash, tessera count, assembly time (ms), file hash |
| Bitfield rebuild | Mosaic hash, tesserae verified, rebuild time (ms) |
| Startup complete | Active transfers resumed, manifest index size, total startup time (ms) |
| Thread pool queueing | Queue depth, when a disk op waited > 10 ms for a thread |

### Development benchmarks

The implementation must include a benchmark suite that validates budgets from sections 2–7 against actual measurements. Benchmarks are not unit tests — they run against real I/O and real MFP channels (loopback).

| Benchmark | What it measures | Budget validated |
|-----------|-----------------|------------------|
| `bench_chunking` | Chunking throughput (MB/s) for 1 MB, 100 MB, 1 GB files | Section 2 (overhead), Section 5 (chunking I/O) |
| `bench_hash` | SHA-256 throughput for 256 KB blocks | Section 6 (hashing cost) |
| `bench_assembly` | Assembly throughput for pre-staged tessera directories | Section 3 (latency), Section 5 (assembly I/O) |
| `bench_single_peer` | End-to-end fetch from one seeder over loopback | Section 2 (single-peer throughput) |
| `bench_multi_peer` | End-to-end fetch from N seeders over loopback | Section 2 (multi-peer scaling) |
| `bench_publish_latency` | Time from `publish()` call to seeding-ready state | Section 3 (publish latency) |
| `bench_resume` | Startup time with N partial transfers on disk | Section 3 (startup latency) |
| `bench_memory` | Peak RSS during fetch of 1 GB file with 50 peers | Section 4 (memory ceiling) |

Benchmarks report results as structured JSON for automated comparison across commits. A budget violation (measured value exceeds budget by > 10%) should be flagged in CI as a warning, not a failure — budgets are targets, and hardware varies.

### Budget review cadence

Performance budgets are living targets. They should be reviewed:

- After the first working prototype delivers end-to-end transfers.
- After any architectural change to the Transfer Engine, storage layer, or concurrency model.
- When the target scale changes (e.g., expanding from hundreds to thousands of peers).

Reviewed budgets are recorded as revisions to this spec with updated `revised` dates.

---

## 9. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| ts-spec-001 | Vision & Scope | NG3 (target scale: tens to hundreds of peers), success criteria |
| ts-spec-005 | Wire Protocol Addendum | PIECE message framing overhead, max_payload constraint |
| ts-spec-006 | Content Addressing | SHA-256 hashing, Merkle tree, manifest size, chunked manifest transfer threshold |
| ts-spec-007 | Swarm & Peer Discovery | max_peers_per_swarm, max_swarms_per_node capacity limits |
| ts-spec-008 | Piece Selection & Transfer | Request pipeline concurrency, rarest-first scan, peer scoring, endgame, TransferStatus |
| ts-spec-009 | AI Integration | AIStatus observability, adapter call latency, graceful degradation |
| ts-spec-010 | API & CLI Design | TesseraConfig defaults, status() API, --json output |
| ts-spec-011 | Storage & State Management | Temp-then-rename pattern, bitfield rebuild, assembly, fsync policy |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
