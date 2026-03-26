# Content Addressing Spec

```yaml
id: ts-spec-006
type: spec
status: stable
created: 2026-03-14
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [content-addressing, manifest, hashing, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Chunking Process
3. Hash Tree Construction
4. Manifest Format
5. Manifest Hashing & Identity
6. Manifest Transfer Strategy
7. Integrity Verification
8. References

---

## 1. Purpose & Scope

This document specifies how Tessera transforms a file into a content-addressed mosaic — the process of chunking, hashing, and manifesting that makes decentralized transfer possible. It is the bridge between the raw file on disk and the wire protocol messages (ts-spec-005) that move tesserae between peers.

### What content addressing provides

Content addressing means that every artifact in Tessera — every tessera, every manifest — is identified by its cryptographic hash, not by a name, path, or location. This yields three properties:

| Property | Mechanism |
|----------|-----------|
| **Integrity** | A tessera's hash proves its contents are correct. No trust in the sender is required — only trust in the manifest, which is itself hash-verified. |
| **Deduplication** | Identical content produces identical hashes. Two publishers sharing the same file produce the same manifest hash, and peers can serve tesserae interchangeably. |
| **Immutability** | A manifest hash is a permanent identifier. The manifest cannot be altered without changing its hash, which makes it a different mosaic entirely (ADR-005). |

### What this spec defines

- **Chunking.** How the Chunker splits a file into fixed-size tesserae, including handling of the final partial tessera and the `ChunkingStrategy` extension point (ADR-004).
- **Hash tree construction.** How SHA-256 leaf hashes are computed from tessera data and combined into a Merkle tree with a single root hash.
- **Manifest format.** The complete field layout of the manifest document — metadata, hash tree, and tessera table.
- **Manifest hashing.** How the manifest hash (the mosaic's identity) is computed from the serialized manifest.
- **Manifest transfer.** How manifests are exchanged between peers, including strategies for large manifests that exceed MFP's payload limit.
- **Integrity verification.** The Piece Verifier's per-tessera check and the Assembler's whole-file check, implementing mitigations for T1 (piece poisoning) and T2 (manifest tampering).

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Wire message format for REQUEST, PIECE, REJECT | ts-spec-005 |
| How peers discover manifest hashes | ts-spec-007 |
| Which tesserae to request first | ts-spec-008 |
| On-disk storage layout for tesserae and manifests | ts-spec-011 |
| Tessera size and other configurable defaults | ts-spec-010 |

### Relationship to prior specs

The Chunker, Assembler, and Piece Verifier are Transfer Engine components defined in ts-spec-004 (section 3.1). This spec details their internal logic. The HANDSHAKE message (ts-spec-005, section 4) carries `tessera_count` and `tessera_size` — values derived from the manifest defined here. The threat model (ts-spec-003) references this spec for T1 and T2 mitigations.

## 2. Chunking Process

The Chunker reads a file sequentially and splits it into tesserae of a fixed size. This section specifies the default algorithm and the extension point for alternative strategies.

### Default algorithm: fixed-size chunking

Given a file of `file_size` bytes and a configured `tessera_size` (default 262,144 bytes / 256 KB):

```
tessera_count = ⌈file_size / tessera_size⌉
```

Tesserae are numbered from index 0 to `tessera_count - 1`. Each tessera contains:

| Index | Byte range | Size |
|-------|-----------|------|
| 0 | `[0, tessera_size)` | `tessera_size` |
| 1 | `[tessera_size, 2 × tessera_size)` | `tessera_size` |
| ... | ... | ... |
| N-2 | `[(N-2) × tessera_size, (N-1) × tessera_size)` | `tessera_size` |
| N-1 | `[(N-1) × tessera_size, file_size)` | `file_size - (N-1) × tessera_size` |

The final tessera (index N-1) may be smaller than `tessera_size`. This is the only tessera whose size may differ. No padding is applied — the final tessera contains exactly the remaining bytes.

### Edge cases

| Case | Behavior |
|------|----------|
| **Empty file** (0 bytes) | `tessera_count = 0`. The manifest has an empty hash tree. The mosaic is immediately complete on creation. The manifest hash is still a valid identifier. |
| **File smaller than tessera_size** | `tessera_count = 1`. A single tessera contains the entire file. |
| **File exactly divisible** | All tesserae are `tessera_size` bytes. No short final tessera. |

### Chunking is deterministic

For the same file content and the same `tessera_size`, the Chunker **must** produce the same sequence of tesserae, the same hashes, and the same manifest. This is what makes content addressing work — two independent publishers chunking the same file produce the same manifest hash, and their tesserae are interchangeable across swarms.

Determinism requires:
- Sequential reads starting from byte 0.
- No reordering of tesserae.
- No internal state carried between files.
- SHA-256 as the sole hash function (no implementation-dependent alternatives).

### ChunkingStrategy extension point

The Chunker accepts an optional `ChunkingStrategy` protocol (ts-spec-004, section 8):

```python
class ChunkingStrategy(Protocol):
    def chunk(self, file_path: Path, tessera_size: int) -> Iterator[bytes]:
        """Yield tessera payloads from the file."""
        ...

    def tessera_count(self, file_path: Path, tessera_size: int) -> int:
        """Return the total number of tesserae without reading the full file."""
        ...
```

The default implementation is `FixedSizeChunking`, which implements the algorithm above. Alternative strategies (e.g., content-defined chunking via Rabin fingerprinting) can be plugged in by providing a different `ChunkingStrategy`. All strategies must satisfy the determinism requirement: same input, same output, every time.

**Constraint:** Regardless of strategy, every tessera produced must satisfy `len(tessera) + 5 ≤ max_payload_size` — the PIECE message size constraint from ts-spec-005, section 6. The Chunker validates this before producing the manifest.

## 3. Hash Tree Construction

The hash tree is a Merkle tree built from tessera hashes. It enables per-tessera integrity verification without requiring the full file, and its root hash anchors the manifest's identity.

### Leaf computation

Each leaf in the hash tree is the SHA-256 hash of a single tessera's raw bytes:

```
leaf[i] = SHA-256(tessera[i].data)
```

Leaf hashes are 32 bytes each. For a mosaic with N tesserae, there are N leaves.

### Tree construction

The tree is built bottom-up by pairing nodes at each level and hashing their concatenation:

```
parent = SHA-256(left_child || right_child)
```

Where `||` denotes byte concatenation. Construction proceeds as follows:

1. **Level 0 (leaves):** N leaf hashes, one per tessera.
2. **Level 1:** ⌈N/2⌉ nodes. Each node is `SHA-256(leaf[2k] || leaf[2k+1])`. If N is odd, the last leaf is **promoted** — it becomes a level-1 node without hashing. It is not duplicated or paired with itself.
3. **Level 2:** ⌈⌈N/2⌉/2⌉ nodes. Same pairing rule applied to level-1 nodes.
4. **Repeat** until a single node remains.
5. **Root:** The final remaining node is the Merkle root hash.

### Odd-node promotion (not duplication)

When a level has an odd number of nodes, the last node is promoted to the next level as-is. It is **not** duplicated and paired with a copy of itself. Duplication would mean that a corrupted last tessera produces a valid hash if an attacker provides the tessera twice — promotion avoids this.

Example with 5 tesserae:

```
Level 0:  L0    L1    L2    L3    L4

Level 1:  H(L0||L1)   H(L2||L3)   L4  ← promoted

Level 2:  H(H(L0||L1) || H(L2||L3))   L4  ← promoted again

Level 3:  H( H(H(L0||L1)||H(L2||L3)) || L4 )  ← root
```

### Special cases

| Case | Hash tree |
|------|-----------|
| **0 tesserae** (empty file) | No leaves, no root. The manifest's `root_hash` field is set to 32 zero bytes (`0x00 × 32`). |
| **1 tessera** | The single leaf hash is the root. No internal nodes. `root_hash = SHA-256(tessera[0].data)`. |
| **2 tesserae** | One internal node: `root_hash = SHA-256(leaf[0] || leaf[1])`. |

### Verification path

To verify tessera *i*, a peer needs the **sibling hashes** along the path from leaf *i* to the root. This is the standard Merkle proof — a sequence of (hash, direction) pairs that, when combined with the tessera's own hash, reconstruct the root.

The manifest includes the full leaf hash list (section 4), so a peer with the manifest can verify any tessera independently. Merkle proofs (partial verification without the full leaf list) are a future optimization — not required in v1, where every peer holds the complete manifest.

### Hash function

SHA-256 is used exclusively for all content addressing:
- Tessera leaf hashes
- Internal Merkle tree nodes
- Manifest hashing (section 5)

Tessera uses Python's `hashlib.sha256`, not MFP's cryptographic primitives. This separation is specified in ts-spec-004 (section 6, MFP Boundary): Tessera's content hashing is independent of MFP's channel encryption.

## 4. Manifest Format

The manifest is a binary document that fully describes a mosaic. It is the single artifact a fetcher needs to join a swarm, verify every tessera, and assemble the complete file.

### Design principles

- **Binary, not text.** The manifest is a compact binary format, not JSON or YAML. This keeps hashing deterministic (no whitespace ambiguity, no key ordering issues) and minimizes size for large mosaics.
- **Fixed header, variable body.** The header is fixed-size for fast parsing. The variable-length sections (metadata, leaf hashes) follow the header.
- **Self-contained.** The manifest includes everything needed for verification — no external lookups required beyond the manifest itself.

### Layout

```
Offset  Size              Field
──────  ────              ─────
0       4                 magic               "TSRA" (0x54535241)
4       2                 format_version      Manifest format version (currently 0x0001)
6       32                root_hash           Merkle tree root hash (SHA-256)
38      4                 tessera_count       Number of tesserae (u32)
42      4                 tessera_size        Default tessera size in bytes (u32)
46      8                 file_size           Original file size in bytes (u64)
54      4                 last_tessera_size   Size of the final tessera in bytes (u32). Equal to tessera_size if file is evenly divisible.
58      2                 metadata_len        Length of the metadata section in bytes (u16)
60      metadata_len      metadata            File metadata (see below)
60+M    32 × N            leaf_hashes         SHA-256 hash of each tessera, in index order
```

Where `M = metadata_len` and `N = tessera_count`.

Total manifest size: `60 + M + 32N` bytes.

### Magic and format version

The magic bytes `TSRA` identify the document as a Tessera manifest. Parsers must reject documents that do not start with these four bytes.

The `format_version` field (currently `0x0001`) allows future changes to the manifest layout. A parser must reject manifests with an unrecognized version.

### Metadata section

The metadata section carries human- and agent-readable information about the file. It is encoded as a sequence of length-prefixed UTF-8 key-value pairs:

```
For each entry:
  1 byte    key_len
  key_len   key       UTF-8 string
  2 bytes   val_len   (u16, big-endian)
  val_len   value     UTF-8 string
```

Entries are written in sorted key order to ensure deterministic serialization. Duplicate keys are not permitted.

#### Defined metadata keys

| Key | Required | Description |
|-----|----------|-------------|
| `name` | Yes | The original filename (without path). |
| `mime` | No | MIME type of the file (e.g., `application/pdf`). |
| `created` | No | ISO 8601 timestamp of when the manifest was created. |
| `description` | No | Free-text description of the file content. |
| `tags` | No | Comma-separated list of tags for discovery. |

Additional keys may be added by publishers. Unknown keys are preserved but not interpreted by the protocol. All metadata values are treated as untrusted input — the sanitization requirements from ts-spec-003 (T9 mitigation) apply before any LLM processing.

**Constraint:** `metadata_len ≤ 65,535` bytes (u16 maximum). This bounds metadata size and prevents manifest bloat. In practice, metadata should be kept small — a few hundred bytes.

### Leaf hashes section

The leaf hashes are stored as a flat array of 32-byte SHA-256 hashes, one per tessera, in index order:

```
leaf_hashes[0]    = SHA-256(tessera[0].data)    — 32 bytes
leaf_hashes[1]    = SHA-256(tessera[1].data)    — 32 bytes
...
leaf_hashes[N-1]  = SHA-256(tessera[N-1].data)  — 32 bytes
```

This section is the largest part of the manifest. Its size is exactly `32 × tessera_count` bytes. For reference:

| File size | Tessera size | Tessera count | Leaf hashes size | Total manifest (approx.) |
|-----------|-------------|--------------|-----------------|------------------------|
| 1 MB | 256 KB | 4 | 128 bytes | ~250 bytes |
| 100 MB | 256 KB | 400 | 12.5 KB | ~13 KB |
| 1 GB | 256 KB | 4,096 | 128 KB | ~128 KB |
| 10 GB | 256 KB | 40,960 | 1.25 MB | ~1.25 MB |
| 1 TB | 256 KB | 4,194,304 | 128 MB | ~128 MB |

The root hash in the manifest header is computed from these leaf hashes using the Merkle tree construction in section 3 — it is **not** stored in the leaf hashes array.

## 5. Manifest Hashing & Identity

The manifest hash is the mosaic's unique, permanent identifier. It is how peers refer to a mosaic in discovery, handshake, and conversation. This section specifies exactly how it is computed.

### Computation

The manifest hash is the SHA-256 hash of the **complete serialized manifest**, including the header, metadata, and leaf hashes:

```
manifest_hash = SHA-256(manifest_bytes)
```

Where `manifest_bytes` is the full binary document from offset 0 through the end of the leaf hashes section — exactly `60 + metadata_len + (32 × tessera_count)` bytes.

There is no canonical re-serialization step. The hash is computed over the byte-for-byte serialized form. Because the manifest format is fully deterministic (fixed field order, sorted metadata keys, no optional padding), two implementations producing a manifest for the same file with the same `tessera_size` **must** produce the same `manifest_hash`.

### What the manifest hash covers

Every field in the manifest contributes to the hash:

| Field | Consequence of tampering |
|-------|------------------------|
| `magic`, `format_version` | A modified magic or version produces a different hash — the manifest is unrecognizable or incompatible. |
| `root_hash` | Changing the root hash changes the manifest hash. A tampered root hash cannot be used to verify tesserae because the fetcher pins the manifest hash, not the root hash. |
| `tessera_count`, `tessera_size`, `file_size`, `last_tessera_size` | Altering any structural field changes the manifest hash. An attacker cannot change the mosaic's geometry without producing a different identity. |
| `metadata` | Modifying the filename, description, or any metadata key-value pair changes the manifest hash. |
| `leaf_hashes` | Substituting, reordering, or adding a leaf hash changes the manifest hash. |

### Immutability guarantee

Because the manifest hash covers the entire document, **any modification to the manifest produces a new hash**, and therefore a new mosaic (ADR-005). There is no mechanism to update a manifest in-place. A publisher who changes a file must re-chunk, re-hash, and re-publish — producing a new manifest hash that identifies a new, distinct mosaic.

This eliminates the T3 (stale manifest replay) tension identified in ts-spec-003: there is no "newer version" of a manifest at the protocol level. Two manifest hashes are either identical (same mosaic) or different (different mosaics).

### Manifest hash as trust anchor

The manifest hash is the single root of trust for a mosaic. The security model depends on the fetcher obtaining the correct manifest hash from a trusted source (TA3 in ts-spec-003). Once a peer has a trusted manifest hash:

1. Any manifest whose SHA-256 does not match is rejected (T2 mitigation).
2. Any tessera whose SHA-256 does not match its leaf hash in the manifest is rejected (T1 mitigation).
3. The root hash in the manifest is verified by recomputing the Merkle tree from the leaf hashes — if it does not match, the manifest is internally inconsistent and rejected.

The chain of trust flows: **manifest hash → manifest → leaf hashes → individual tesserae**.

## 6. Manifest Transfer Strategy

The manifest must reach the fetcher before any tessera exchange can begin. For small mosaics, the manifest fits in a single MFP message. For large mosaics, it does not. This section defines how manifests are exchanged across the full size range.

### Size thresholds

From section 4, manifest size is `60 + M + 32N` bytes. The critical threshold is MFP's `max_payload_size` (default 1 MB):

| File size | Tessera count (256 KB) | Manifest size (approx.) | Fits in 1 MB? |
|-----------|----------------------|------------------------|---------------|
| ≤ 8 GB | ≤ 32,736 | ≤ 1 MB | Yes |
| 10 GB | 40,960 | ~1.25 MB | No |
| 100 GB | 409,600 | ~12.5 MB | No |
| 1 TB | 4,194,304 | ~128 MB | No |

The vast majority of mosaics at the target scale (tens-to-hundreds of peers, per NG3) will have manifests well under 1 MB. The large-manifest strategy exists for completeness and forward compatibility.

### Strategy 1: Inline manifest (default)

When the serialized manifest fits within `max_payload_size`, it is sent as a single MFP message during the swarm join handshake.

**Flow:**

1. Fetcher establishes an MFP channel with a seeder.
2. Fetcher sends HANDSHAKE (ts-spec-005) containing the manifest hash.
3. Seeder replies with HANDSHAKE.
4. If the fetcher does not yet have the manifest, the seeder sends the full manifest as a raw binary payload in a dedicated message type.

This requires a wire message to carry the manifest. A new message type is **not** defined in ts-spec-005 for this — instead, the manifest is requested and delivered using a simple convention on the existing channel:

- The fetcher signals it needs the manifest by setting `tessera_count = 0` in its HANDSHAKE. A seeder receiving a HANDSHAKE with `tessera_count = 0` understands the peer needs the manifest before proceeding.
- The seeder responds with a PIECE message using the reserved index `0xFFFFFFFF` (u32 max), with the manifest bytes as the data payload. This avoids adding a new message type while keeping the manifest transfer within the existing wire protocol.
- The fetcher verifies `SHA-256(data) == manifest_hash` from the HANDSHAKE. On mismatch, the manifest is rejected (T2 mitigation) and the channel is closed.
- After receiving and verifying the manifest, the fetcher re-sends HANDSHAKE with the correct `tessera_count` and `tessera_size` from the manifest, then proceeds to BITFIELD exchange.

### Strategy 2: Chunked manifest

When the manifest exceeds `max_payload_size`, it is split into chunks and delivered as multiple PIECE messages using reserved indices.

**Convention:**

- Manifest chunks use reserved indices starting from `0xFFFFFFFF` and counting downward: `0xFFFFFFFF` (chunk 0), `0xFFFFFFFE` (chunk 1), etc.
- Each chunk is at most `max_payload_size - 5` bytes (the PIECE header overhead).
- The number of chunks is `⌈manifest_size / (max_payload_size - 5)⌉`.
- The fetcher reassembles the chunks in index order (highest reserved index first) and verifies the complete manifest against the manifest hash.
- The seeder includes the chunk count in its HANDSHAKE response by encoding it in the `tessera_size` field when `tessera_count = 0` in the fetcher's HANDSHAKE. This tells the fetcher how many manifest chunks to expect.

### Strategy 3: Out-of-band manifest

For extremely large mosaics or scenarios where channel bandwidth is precious, the manifest may be obtained outside the Tessera wire protocol entirely — via a URL, a shared filesystem, or a separate file transfer. In this case:

- The fetcher already has the manifest before establishing any channel.
- The fetcher sends a normal HANDSHAKE with the correct `tessera_count` and `tessera_size`.
- No manifest transfer occurs on the channel.
- The fetcher is responsible for verifying `SHA-256(manifest_bytes) == manifest_hash`.

Out-of-band manifest distribution is not specified by this protocol — it is the deployer's responsibility. The protocol only requires that the fetcher possesses a verified manifest before entering the transfer phase.

### Strategy selection

| Condition | Strategy |
|-----------|----------|
| Fetcher has manifest | No transfer needed. Normal HANDSHAKE. |
| Fetcher lacks manifest, manifest ≤ `max_payload_size` | Inline (strategy 1). |
| Fetcher lacks manifest, manifest > `max_payload_size` | Chunked (strategy 2). |
| Deployer prefers external distribution | Out-of-band (strategy 3). |

## 7. Integrity Verification

Integrity verification is the enforcement layer of content addressing. It ensures that every byte of the assembled mosaic matches what the publisher originally chunked. Verification happens at three levels, each catching a different class of corruption.

### Level 1: Manifest verification

Performed once, when the fetcher first receives the manifest.

**Steps:**

1. Compute `SHA-256(manifest_bytes)` over the raw received bytes.
2. Compare against the trusted `manifest_hash` (obtained via HANDSHAKE or out-of-band).
3. If mismatch: reject the manifest, close the channel, try another peer. This is the T2 (manifest tampering) mitigation.
4. If match: parse the manifest header and validate structural consistency:
   - `magic` == `TSRA`
   - `format_version` is supported
   - `tessera_count` == number of leaf hashes present
   - `file_size` is consistent with `tessera_count`, `tessera_size`, and `last_tessera_size`:
     - If `tessera_count == 0`: `file_size` must be 0
     - If `tessera_count == 1`: `file_size == last_tessera_size`
     - If `tessera_count > 1`: `file_size == (tessera_count - 1) × tessera_size + last_tessera_size`
   - `last_tessera_size ≤ tessera_size`
5. Recompute the Merkle root from the leaf hashes (section 3) and compare against the `root_hash` field. If mismatch: the manifest is internally inconsistent — reject it.

After passing all checks, the manifest is trusted for the remainder of the transfer.

### Level 2: Per-tessera verification

Performed on every received PIECE message by the Piece Verifier.

**Steps:**

1. Extract `index` and `data` from the PIECE message.
2. Validate `index < tessera_count`. If out of range: send REJECT with `INDEX_OUT_OF_RANGE`.
3. Validate `len(data)` matches expected size:
   - If `index < tessera_count - 1`: `len(data) == tessera_size`
   - If `index == tessera_count - 1`: `len(data) == last_tessera_size`
   - If size mismatch: reject without hashing (fast fail).
4. Compute `SHA-256(data)`.
5. Compare against `leaf_hashes[index]` from the manifest.
6. If match: pass the tessera to the Assembler for disk write.
7. If mismatch: send REJECT with `HASH_MISMATCH`, score the sending peer down (Peer Scorer), and re-request the tessera from another peer. This is the T1 (piece poisoning) mitigation.

Per-tessera verification is the most frequently executed check — it runs once per received tessera. The SHA-256 computation is the dominant cost. For a 256 KB tessera, hashing takes approximately 0.5–1 ms on modern hardware. If this becomes a bottleneck, hashing can be offloaded to a thread pool via `asyncio.to_thread()` (ADR-003).

### Level 3: Whole-file verification

Performed once, after all tesserae have been received and written to disk by the Assembler.

**Steps:**

1. Read the assembled file sequentially from disk.
2. Re-chunk into tesserae using the same `tessera_size`.
3. Compute SHA-256 of each tessera and compare against the manifest's leaf hashes.
4. If all match: the mosaic is complete and verified. Mark as complete, transition from leecher to seeder.
5. If any mismatch: a tessera was corrupted after verification (disk error, race condition, or post-write tampering). Identify the corrupted tessera(s), delete them from disk, reset their bitfield bits, and re-request from peers.

Whole-file verification is a defense-in-depth measure. Per-tessera verification (level 2) should catch all corruption at receive time. Whole-file verification guards against the narrow window between verification and disk write, and against post-write corruption (partial mitigation for TA5 violations).

### Verification summary

| Level | When | What | Catches |
|-------|------|------|---------|
| 1 — Manifest | On manifest receipt | `SHA-256(manifest) == manifest_hash`, structural consistency, root hash recomputation | T2 (manifest tampering), malformed manifests |
| 2 — Per-tessera | On each PIECE receipt | `SHA-256(data) == leaf_hashes[index]` | T1 (piece poisoning), corrupted transfers |
| 3 — Whole-file | On mosaic completion | Re-hash all tesserae from disk, compare against manifest | Post-write corruption, disk errors |

---

## 8. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Goals G2 (end-to-end chunk encryption), G3 (anti-replay/anti-forgery); NG4 (mosaic = single file) |
| R2 | ts-spec-002 — Glossary | Defines tessera, mosaic, manifest, manifest hash, hash tree, publisher, publish, fetch |
| R3 | ts-spec-003 — Threat Model | T1 (piece poisoning) and T2 (manifest tampering) mitigations implemented by integrity verification; T9 (prompt injection via metadata) requiring metadata sanitization; TA3 (manifest obtained from trusted source) as trust anchor |
| R4 | ts-spec-004 — System Architecture | Chunker, Assembler, Piece Verifier component definitions; ChunkingStrategy extension point (ADR-004); MFP Boundary rules for hash function usage |
| R5 | ts-spec-005 — Wire Protocol Addendum | PIECE message layout (section 4), HANDSHAKE fields (tessera_count, tessera_size), REJECT error codes (HASH_MISMATCH, INDEX_OUT_OF_RANGE), payload size constraints (section 6) |
| R6 | ts-spec-007 — Swarm & Peer Discovery | Swarm join process where manifest transfer occurs |
| R7 | ts-spec-008 — Piece Selection & Transfer Strategy | Peer scoring on hash mismatch; re-request logic after tessera rejection |
| R8 | ts-spec-010 — API & CLI Design | TesseraConfig defaults for tessera_size |
| R9 | ts-spec-011 — Storage & State Management | On-disk layout for tesserae, manifests, and incomplete mosaics |
| R10 | ADR-004 — Fixed-Size Tesserae with Extensible Chunking | Decision record for default chunking strategy |
| R11 | ADR-005 — Immutable Manifests | Decision record for manifest immutability |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
