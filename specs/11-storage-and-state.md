# Storage & State Management

```yaml
id: ts-spec-011
type: spec
status: stable
created: 2026-03-17
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [storage, state, persistence, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Directory Layout
3. Manifest Store
4. Tessera Store
5. Transfer State & Resume
6. Concurrency & Crash Recovery
7. Garbage Collection
8. References

## 1. Purpose & Scope

This document defines how Tessera persists data to disk — where files go, how they are organized, and how state is recovered after a crash or restart. It is the owner of `data_dir` (ts-spec-010) and the authority on every file and directory Tessera creates.

### What this spec defines

- **Directory layout.** The structure under `data_dir` (`~/.tessera` by default). Where manifests, tesserae, transfer state, and logs are stored.
- **Manifest store.** How serialized manifests are persisted and looked up by manifest hash.
- **Tessera store.** How downloaded and locally-chunked tesserae are stored on disk, including partial pieces and completed pieces.
- **Transfer state & resume.** The on-disk representation of in-progress transfers — bitfields, peer lists, retry counts — that enables resumption after a node restart without re-downloading completed pieces.
- **Concurrency & crash recovery.** How concurrent reads/writes to the store are coordinated, and how the store self-heals after an unclean shutdown (killed process, power loss, disk full).
- **Garbage collection.** When and how completed transfers, orphaned tesserae, and expired manifests are cleaned up.

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Manifest binary format | ts-spec-006 |
| Wire protocol for piece transfer | ts-spec-005 |
| Swarm state machine (PENDING → CLOSED) | ts-spec-007 |
| TesseraConfig fields (data_dir, etc.) | ts-spec-010 |
| Transfer Engine request pipeline | ts-spec-008 |
| Performance targets for disk I/O | ts-spec-012 |

### Design principles

- **Resumable by default.** A node that crashes mid-transfer and restarts should resume from where it left off, not re-download everything. This is the single most important property of the storage layer.
- **No external dependencies.** The store uses flat files and atomic filesystem operations. No database, no WAL library, no dependency beyond Python's standard library and the OS filesystem.
- **Crash-safe writes.** Every mutation follows a write-to-temp-then-rename pattern. A crash at any point leaves the store in a consistent state — either the old data or the new data, never a partial write.
- **Content-addressable.** Tesserae and manifests are stored by their hash. Duplicate detection is free — if the file exists at the expected path, it is already correct.

---

## 2. Directory Layout

All Tessera state lives under `data_dir` (default `~/.tessera`). The directory is created on first `TesseraNode.start()` if it does not exist.

```
~/.tessera/
├── manifests/                  # Manifest store
│   ├── a3/
│   │   └── a3f2...c891.manifest
│   └── b8/
│       └── b8e1...4d20.manifest
├── tesserae/                   # Tessera store (per-mosaic)
│   ├── a3f2...c891/
│   │   ├── 000000.piece
│   │   ├── 000001.piece
│   │   └── ...
│   └── b8e1...4d20/
│       └── ...
├── transfers/                  # Active transfer state
│   ├── a3f2...c891.state
│   └── b8e1...4d20.state
├── tmp/                        # Temporary files (atomic writes)
└── node.id                     # Persistent node identity
```

### Path conventions

- **Manifest paths** use a 2-character hex prefix directory (first byte of the hash) to avoid large flat directories. File name is the full hex-encoded manifest hash with `.manifest` extension.
  - Example: hash `a3f2...c891` → `manifests/a3/a3f2...c891.manifest`

- **Tessera paths** are grouped by mosaic (manifest hash). Each tessera is named by its zero-padded 6-digit decimal index with `.piece` extension.
  - Example: tessera 42 of mosaic `a3f2...c891` → `tesserae/a3f2...c891/000042.piece`

- **Transfer state** files are named by manifest hash with `.state` extension. One file per active or paused transfer.

- **Temporary files** are created in `tmp/` with a random suffix. Every write operation targets `tmp/` first, then renames to the final path. The `tmp/` directory is cleaned on startup — any files found there are remnants of interrupted writes and are deleted.

### node.id

A 32-byte file containing the node's persistent identity seed. Created once on first startup via `os.urandom(32)`. Used to derive deterministic values that must survive restarts (e.g., tracker announce tokens). This is not an MFP AgentId — the MFP agent is created fresh each session. `node.id` is a Tessera-level concept for correlating sessions.

### Permissions

Tessera creates directories with mode `0o700` and files with mode `0o600`. The `data_dir` contains cryptographic material (`node.id`) and downloaded content — it should not be world-readable.

---

## 3. Manifest Store

The manifest store persists serialized manifests (ts-spec-006) so they survive node restarts. A manifest is written once and never modified (ADR-005: immutable manifests).

### Write path

1. Serialize the manifest to its binary format (ts-spec-006, section 4).
2. Compute the SHA-256 hash of the serialized bytes — this is the manifest hash.
3. Derive the storage path: `manifests/{hash[0:2]}/{hash_hex}.manifest`.
4. If the file already exists at that path, skip — the manifest is already stored. Content-addressability guarantees correctness.
5. Write the serialized bytes to `tmp/{random}.manifest`.
6. `os.rename()` the temp file to the final path. On POSIX, this is atomic.

### Read path

1. Derive the storage path from the manifest hash.
2. Read the file. If it does not exist, return `None`.
3. Verify: compute SHA-256 of the bytes read and compare to the expected hash. If they differ, the file is corrupt — delete it and return `None`.

The verification step on read defends against silent disk corruption. The caller (typically the Transfer Engine) treats a missing manifest the same as a corrupt one — re-request from peers.

### Manifest index

The manifest store maintains an in-memory index for the AI Discovery Adapter (ts-spec-009). The index maps manifest hashes to their metadata key-value pairs, enabling natural-language search without deserializing every manifest on disk.

```python
class ManifestIndex:
    """In-memory index of manifest metadata, rebuilt on startup."""

    def rebuild(self) -> None:
        """Scan manifests/ and extract metadata from each file."""

    def add(self, manifest_hash: bytes, metadata: dict[str, str]) -> None:
        """Add a manifest to the index (called after write)."""

    def remove(self, manifest_hash: bytes) -> None:
        """Remove a manifest from the index (called during GC)."""

    def all_metadata(self) -> list[tuple[bytes, dict[str, str]]]:
        """Return all (hash, metadata) pairs for LLM search."""
```

The index is rebuilt from disk on every `TesseraNode.start()`. It is not persisted — the manifests themselves are the source of truth. Rebuild cost is linear in the number of stored manifests; at the target scale (tens to hundreds of mosaics), this completes in milliseconds.

### Disk budget

A manifest is small — the fixed header is 60 bytes, metadata is typically under 1 KB, and the leaf hash array is `32 × tessera_count` bytes. A 1 GB file chunked at 256 KB produces ~4,000 tesserae, yielding a ~128 KB manifest. The manifest store will not be a meaningful consumer of disk space.

---

## 4. Tessera Store

The tessera store holds the actual file chunks — both locally-chunked pieces (publisher) and downloaded pieces (fetcher). It is the largest consumer of disk space and the most write-intensive component.

### Storage layout

Tesserae are grouped by mosaic. Each mosaic gets a directory named by its full hex-encoded manifest hash under `tesserae/`:

```
tesserae/a3f2...c891/
├── 000000.piece
├── 000001.piece
├── 000002.piece
└── ...
```

File names are the zero-padded 6-digit decimal tessera index. This supports mosaics up to 999,999 tesserae (256 KB × 999,999 ≈ 244 GB), well beyond typical use at the target scale.

### Write path (download)

1. Receive piece data from a peer via PIECE message (ts-spec-005).
2. Compute SHA-256 of the piece data.
3. Compare against the expected leaf hash from the manifest (ts-spec-006, section 5). If mismatch, discard and report to peer scoring (ts-spec-008).
4. Write piece data to `tmp/{random}.piece`.
5. `os.rename()` to `tesserae/{manifest_hash_hex}/{index:06d}.piece`.
6. Update the in-memory bitfield and transfer state (section 5).

If the target file already exists (step 5), the write is skipped. This handles duplicate deliveries during endgame mode (ts-spec-008, section 6) without redundant I/O.

### Write path (publish)

1. The Chunker (ts-spec-004) reads the source file and yields tesserae sequentially.
2. Each tessera is hashed and written to `tesserae/{manifest_hash_hex}/{index:06d}.piece` via the same temp-then-rename pattern.
3. The leaf hashes are collected to build the manifest (ts-spec-006).

The publisher's tesserae are identical to what a fetcher would download — the store is symmetric.

### Read path

1. Derive the path from manifest hash and tessera index.
2. Read the file. If it does not exist, return `None` (the tessera has not been downloaded yet).
3. No hash verification on read by default. The tessera was verified on write; re-verification on every read would be prohibitively expensive during assembly. The whole-file verification after assembly (ts-spec-006, section 7) catches any disk corruption that occurs between write and read.

### Assembly

When all tesserae for a mosaic are present (bitfield is complete):

1. Open the output file for writing.
2. Iterate tessera indices 0 through N-1.
3. Read each `.piece` file and append to the output file.
4. Compute SHA-256 of the complete output file.
5. Compare against the manifest's `file_hash`. If mismatch, raise `IntegrityError` (ts-spec-010).
6. On success, fire the `on_transfer_complete` callback (ts-spec-010, section 6).

Assembly reads are sequential, which is optimal for both spinning disks and SSDs. The Assembler does not need to seek.

### Disk usage

The tessera store holds a full copy of every mosaic the node is seeding or downloading. For a fetcher, disk usage equals the sum of all active and completed mosaic sizes. For a publisher, the tesserae duplicate the source file's content on disk. Garbage collection (section 7) reclaims space for completed transfers the node no longer seeds.

---

## 5. Transfer State & Resume

Transfer state files enable resumption after a crash or restart. Each active transfer (publish or fetch) has a corresponding `.state` file in `transfers/`.

### State file format

Transfer state is serialized as a JSON object. JSON is chosen over a binary format because state files are small (< 10 KB), human-inspectable for debugging, and written infrequently relative to piece I/O.

```json
{
  "version": 1,
  "manifest_hash": "a3f2...c891",
  "role": "fetcher",
  "tessera_count": 200,
  "bitfield": "//////////8AAAAAAAAAAAAAAAAAAAAAAAAA",
  "created_at": "2026-03-17T14:30:00Z",
  "updated_at": "2026-03-17T14:32:15Z",
  "bytes_downloaded": 41943040,
  "retry_counts": {"142": 2, "187": 1},
  "stuck_tesserae": [],
  "peers_seen": ["agent_id_hex_1", "agent_id_hex_2"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | State file format version. Always `1`. |
| `manifest_hash` | str | Hex-encoded manifest hash. |
| `role` | str | `"seeder"` or `"fetcher"`. |
| `tessera_count` | int | Total number of tesserae in the mosaic. |
| `bitfield` | str | Base64-encoded bitfield. Bit *i* is set if tessera *i* is on disk. |
| `created_at` | str | ISO 8601 timestamp of transfer start. |
| `updated_at` | str | ISO 8601 timestamp of last state write. |
| `bytes_downloaded` | int | Total bytes written to tessera store for this mosaic. |
| `retry_counts` | dict | Map of tessera index (string) → retry count for tesserae that have been retried. |
| `stuck_tesserae` | list | Indices of tesserae that exceeded `max_retries_per_tessera`. |
| `peers_seen` | list | Hex-encoded AgentIds of peers encountered during this transfer. Informational — not used for reconnection. |

### Write policy

State files are not written after every piece. The overhead of serializing and renaming on every tessera completion would dominate I/O for fast transfers. Instead, state is persisted:

1. **On significant progress** — every 5% of total tesserae completed (configurable as a compile-time constant, not a TesseraConfig field).
2. **On swarm state transitions** — when the swarm moves to DRAINING or CLOSED.
3. **On graceful shutdown** — during `TesseraNode.stop()`, before the MFP agent unbinds.
4. **On retry escalation** — when a tessera's retry count crosses `max_retries_per_tessera / 2`, to capture the anomaly.

In the worst case (crash between state writes), the node loses awareness of at most 5% of completed tesserae. On resume, it discovers them on disk (see below) and does not re-download them.

### Write path

1. Build the JSON object from in-memory transfer state.
2. Serialize to bytes.
3. Write to `tmp/{random}.state`.
4. `os.rename()` to `transfers/{manifest_hash_hex}.state`.

### Resume on startup

When `TesseraNode.start()` is called:

1. Scan `transfers/` for `.state` files.
2. For each state file:
   a. Parse the JSON. If malformed, log a warning and delete the file.
   b. Verify the corresponding manifest exists in the manifest store. If not, the transfer cannot resume — delete the state file and its tessera directory.
   c. Rebuild the bitfield from disk: scan `tesserae/{manifest_hash_hex}/` and set bit *i* for every `{i:06d}.piece` file that exists and passes hash verification against the manifest.
   d. The disk-derived bitfield is authoritative — it may have more bits set than the state file's bitfield (pieces completed after the last state write) or fewer (if a piece file was lost to disk corruption).
   e. If the disk-derived bitfield is complete, the transfer is already done. Run assembly (section 4) and delete the state file.
   f. Otherwise, restore the transfer as a paused swarm. The Swarm Manager re-announces to discovery and resumes piece selection from the updated bitfield.

### Seeder state

Publishers also get state files with `role: "seeder"`. The bitfield is always complete (all bits set). The state file's purpose is to tell the node on restart which mosaics to re-announce and seed. A seeder state file is deleted when the user cancels seeding or garbage collection removes the mosaic.

---

## 6. Concurrency & Crash Recovery

### Concurrency model

The storage layer serves multiple swarms concurrently. Each swarm's Transfer Engine writes tesserae and state files independently. The concurrency guarantees are:

- **No cross-mosaic contention.** Each mosaic has its own tessera directory and its own state file. Two swarms never write to the same file.
- **Within-mosaic ordering.** Within a single swarm, piece writes are concurrent (multiple peers deliver pieces simultaneously). This is safe because each tessera has a unique index and therefore a unique file path — no two writes target the same file.
- **State file serialization.** State file writes for a given mosaic are serialized by the Transfer Engine's event loop. Only one state write is in flight per mosaic at any time.
- **Manifest store is append-only.** Manifests are written once. Concurrent reads are safe. The only mutation is deletion during garbage collection, which is serialized (section 7).

No file-level locking is needed. The combination of content-addressable paths (no collisions), atomic rename (no partial reads), and single-writer-per-file (no races) eliminates lock contention without explicit synchronization.

### Disk I/O threading

All disk operations — tessera reads, tessera writes, state file writes, assembly — run via `asyncio.to_thread()` (ADR-003). This keeps the event loop free for network I/O while disk operations block in the thread pool. The default thread pool size (`min(32, os.cpu_count() + 4)`) is sufficient for the target scale.

### Crash recovery

Tessera's crash recovery relies on two properties: atomic rename and content-addressable storage. Together they guarantee that the store is always in a consistent state, even after an unclean shutdown.

#### Scenario: crash during tessera write

- The temp file in `tmp/` exists but was never renamed.
- On startup, `tmp/` is cleaned — the incomplete file is deleted.
- The tessera is missing from the mosaic directory. The bitfield rebuild (section 5) does not set that bit. The Transfer Engine re-requests the tessera from peers.
- **Result:** no data corruption. At most one tessera is re-downloaded.

#### Scenario: crash during state file write

- The temp file in `tmp/` exists but was never renamed.
- The previous `.state` file in `transfers/` is intact (rename is atomic — the old file is either fully replaced or untouched).
- On startup, the old state file is loaded. The bitfield rebuild from disk may find more pieces than the state file records. The disk-derived bitfield takes precedence.
- **Result:** no data loss. State may be slightly stale, but disk scan corrects it.

#### Scenario: crash during assembly

- The output file may be partially written or absent.
- The tessera directory is intact — individual `.piece` files were never modified during assembly.
- On startup, the state file still exists (it is deleted only after successful assembly). Resume detects all tesserae present, re-runs assembly.
- **Result:** assembly is retried from scratch. No re-download needed.

#### Scenario: disk full during write

- `os.rename()` may fail if the filesystem is full (rename requires directory entry space).
- If the temp file was written but rename failed, the temp file remains in `tmp/` and is cleaned on next startup.
- The Transfer Engine catches `OSError` from the write path, logs it at `error` level, and pauses the swarm. The swarm transitions to DRAINING until disk space is freed. It does not retry in a tight loop.
- **Result:** no corruption. Transfer pauses until the condition is resolved.

#### Scenario: corrupt piece file on disk

- Silent bit rot corrupts a `.piece` file between write and assembly.
- During assembly, the whole-file hash check (section 4, step 4) fails.
- The Assembler does not know which tessera is corrupt. It deletes the output file, clears the entire bitfield, and re-verifies each tessera individually by hashing it against the manifest's leaf hashes.
- Corrupt tesserae are deleted and their bits cleared. The Transfer Engine re-requests only the affected pieces.
- **Result:** self-healing. Only corrupt pieces are re-downloaded.

---

## 7. Garbage Collection

Garbage collection reclaims disk space from mosaics the node no longer needs to store. It is explicit, not automatic — Tessera does not silently delete data the user may want to keep.

### What is eligible for collection

A mosaic's on-disk data (manifest, tesserae, state file) becomes eligible for garbage collection when:

1. **The swarm is CLOSED.** The node has left the swarm and is neither seeding nor fetching.
2. **The transfer completed successfully** and the assembled file has been written to the output path. The tesserae are now redundant — the complete file exists elsewhere on disk.
3. **The user explicitly cancelled** a transfer via `TesseraNode.cancel()` or `tessera cancel`. Partial tesserae are orphaned.

A mosaic that is actively seeding (`role: "seeder"`, swarm state ACTIVE) is never eligible. The publisher must stop seeding before its data can be collected.

### Collection triggers

Garbage collection runs in two modes:

**Automatic (post-transfer).** After a successful fetch completes and the output file is verified, the node schedules a deferred cleanup of that mosaic's tesserae. The cleanup runs after a grace period of 60 seconds, giving the node time to transition to seeding if desired. If the node begins seeding the mosaic within the grace period, the cleanup is cancelled.

**Manual (CLI / API).** A future `tessera gc` command and `TesseraNode.gc()` method allow explicit cleanup. These are not defined in this spec — they will be added as the implementation matures. For v1, automatic post-transfer cleanup and cancellation cleanup are sufficient.

### Collection procedure

1. Verify the mosaic is eligible (no active swarm, no seeder state file).
2. Delete the transfer state file: `transfers/{manifest_hash_hex}.state`.
3. Delete all tessera files: `tesserae/{manifest_hash_hex}/*.piece`.
4. Delete the mosaic's tessera directory: `tesserae/{manifest_hash_hex}/`.
5. Remove the manifest from the in-memory index (section 3).
6. Optionally delete the manifest file. By default, manifests are retained — they are small and allow the node to re-join the swarm later without re-fetching the manifest. A `retain_manifests: bool` flag on the collection call controls this.

Steps 2–4 are not atomic. If the node crashes mid-collection, the next startup finds an orphaned tessera directory with no state file. The startup scan (section 5, step 2b) detects this — no matching state file means no transfer to resume. The orphaned directory is logged as a warning but not automatically deleted (it may contain data the user wants to inspect). The future `tessera gc` command will clean these up.

### Startup cleanup

On `TesseraNode.start()`, before resuming transfers:

1. **Clean `tmp/`.** Delete all files in the temporary directory. These are remnants of interrupted atomic writes.
2. **Scan for orphaned tessera directories.** A tessera directory with no corresponding state file and no matching manifest is orphaned. Log a warning with the directory path. Do not delete automatically.
3. **Scan for stale state files.** A state file whose manifest is missing from the manifest store cannot be resumed. Delete the state file and its tessera directory (if any), log at `info` level.

---

## 8. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| ts-spec-004 | System Architecture | Chunker, Assembler, Transfer Engine component definitions |
| ts-spec-005 | Wire Protocol Addendum | PIECE message format for tessera delivery |
| ts-spec-006 | Content Addressing | Manifest binary format, leaf hashes, whole-file verification, chunking |
| ts-spec-007 | Swarm & Peer Discovery | Swarm state machine (ACTIVE, DRAINING, CLOSED), re-announcement on resume |
| ts-spec-008 | Piece Selection & Transfer | Peer scoring (hash mismatch reporting), request pipeline, endgame duplicate handling |
| ts-spec-009 | AI Integration | ManifestIndex consumed by Discovery Adapter for natural-language search |
| ts-spec-010 | API & CLI Design | data_dir config field, IntegrityError, on_transfer_complete callback, cancel() |
| ts-spec-012 | Performance Budget | Disk I/O targets (forward reference) |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
