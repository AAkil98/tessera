# Wire Protocol Addendum

```yaml
id: ts-spec-005
type: spec
status: draft
created: 2026-03-14
revised: 2026-03-14
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [wire-protocol, messaging, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Relationship to MFP Wire Format
3. Message Types
4. Message Encoding
5. Message Flow Diagrams
6. Payload Size Constraints
7. Error & Rejection Messages
8. Extensibility
9. References

---

## 1. Purpose & Scope

This document defines the application-layer message format that Tessera peers exchange over MFP channels. It is an **addendum** to MFP's wire protocol, not a replacement — MFP owns the transport envelope, encryption, and frame structure; Tessera owns the plaintext payload inside.

### What MFP provides (not specified here)

MFP delivers every Tessera message through a pipeline that is fully transparent to this spec:

| Concern | MFP Mechanism |
|---------|---------------|
| Wire framing | 64-byte envelope header + symmetric frame pair (k blocks × 16 bytes each) |
| Payload encryption | AES-256-GCM with per-message nonce derived from channel ID and step counter |
| Authentication | Frame binding via HMAC-SHA256; sender identity proven by key possession |
| Replay protection | Monotonic step counter advanced by the temporal ratchet |
| Channel management | `establish_channel()`, `mfp_send()`, `mfp_channels()` |

From MFP's perspective, every Tessera message is an opaque `bytes` payload passed to `mfp_send()`. MFP encrypts, frames, transmits, validates, decrypts, and delivers it — without inspecting or interpreting the contents.

### What this spec defines

This document specifies the structure **inside** that opaque payload:

- **Message type discrimination.** A type tag that tells the receiver how to interpret the remaining bytes.
- **Field layouts.** The serialization format for each message type — handshake, bitfield, request, piece, have, cancel, and reject.
- **Message flow sequences.** The expected order of messages during swarm join, piece exchange, and endgame.
- **Payload size constraints.** How tessera size, manifest size, and MFP's `max_payload` (default 1 MB, hard limit 10 MB) interact.
- **Error and rejection semantics.** Protocol-level error codes and their meaning.
- **Extensibility.** How new message types can be introduced without breaking existing peers.

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Manifest format, hash tree construction, content addressing | ts-spec-006 |
| Discovery protocol (how peers find each other before channels exist) | ts-spec-007 |
| Piece selection algorithms (which tessera to request next) | ts-spec-008 |
| AI-driven message hints or metadata enrichment | ts-spec-009 |
| Configuration defaults (tessera size, concurrency limits) | ts-spec-010 |

## 2. Relationship to MFP Wire Format

Tessera messages occupy a single layer in MFP's protocol stack. Understanding where Tessera sits — and what it must never touch — is essential to the rest of this spec.

### Message nesting

A Tessera message on the wire is nested inside MFP's envelope:

```
┌──────────────────────────────────────────────────────────────┐
│  MFP Envelope Header (64 bytes, cleartext)                   │
│  magic("MFP1") · version · flags · frame_depth · payload_len │
│  channel_id · step · sender_runtime · reserved               │
├──────────────────────────────────────────────────────────────┤
│  Frame Open (frame_depth × 16 bytes)                         │
├──────────────────────────────────────────────────────────────┤
│  Encrypted Payload (AES-256-GCM)                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │  Tessera Message (plaintext, after decryption)           ││
│  │  ┌──────────┬───────────────────────────────────────────┐││
│  │  │ msg_type │              message body                 │││
│  │  │ (1 byte) │         (variable length)                 │││
│  │  └──────────┴───────────────────────────────────────────┘││
│  └──────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────┤
│  Frame Close (frame_depth × 16 bytes, mirror of Frame Open)  │
└──────────────────────────────────────────────────────────────┘
```

The boundary is clean: MFP sees `bytes`, Tessera sees structured messages. Neither layer inspects the other's fields.

### One Tessera message per MFP message

Each call to `mfp_send(handle, channel_id, payload)` carries exactly one Tessera message. Tessera does not batch multiple messages into a single MFP payload and does not split a single message across multiple MFP sends. This simplifies framing — the Tessera message boundary is always the MFP message boundary.

### What Tessera inherits for free

Because every Tessera message travels inside an MFP frame, the following properties hold without any Tessera-side implementation:

| Property | Guarantee |
|----------|-----------|
| **Confidentiality** | Payload is AES-256-GCM encrypted. Network observers see ciphertext only. |
| **Integrity** | GCM authentication tag detects any modification in transit. |
| **Authentication** | The sender's identity (AgentId) is cryptographically bound to the channel. A forged sender cannot produce valid frames. |
| **Replay protection** | The ratchet's monotonic step counter ensures each frame is unique. Replayed frames are rejected before decryption. |
| **Ordering** | Step counters provide a total order per channel. Out-of-order delivery is detectable. |
| **Peer isolation** | Each channel is an independent encrypted pipe. Messages on channel A are invisible to peers on channel B. |

### What Tessera must handle itself

MFP is message-type-agnostic. The following are Tessera's responsibility:

| Concern | Tessera's job |
|---------|---------------|
| **Message type dispatch** | Interpret the `msg_type` byte and route to the correct handler. |
| **Field parsing** | Deserialize the message body according to the type-specific layout. |
| **Semantic validation** | Reject messages that are syntactically valid but semantically wrong (e.g., a REQUEST for a tessera index beyond the manifest's range). |
| **State machine enforcement** | Ensure messages arrive in a valid order (e.g., HANDSHAKE before BITFIELD before REQUEST). |
| **Application-level errors** | Generate and handle REJECT messages for protocol violations that MFP cannot detect. |

## 3. Message Types

Tessera defines eight message types. Each is identified by a single-byte `msg_type` tag at offset 0 of the plaintext payload.

### Type registry

| msg_type | Name | Direction | Purpose |
|----------|------|-----------|---------|
| `0x01` | HANDSHAKE | Bidirectional | Initiate a peer session. Exchange manifest hash and protocol version. |
| `0x02` | BITFIELD | Bidirectional | Declare which tesserae the sender currently holds. Sent once, immediately after HANDSHAKE. |
| `0x03` | REQUEST | Fetcher → Seeder | Request one or more tesserae by index. |
| `0x04` | PIECE | Seeder → Fetcher | Deliver a single tessera payload with its index and hash. |
| `0x05` | HAVE | Bidirectional | Announce that the sender has acquired a new tessera. Sent after successful verification of a received piece. |
| `0x06` | CANCEL | Fetcher → Seeder | Cancel a previously sent REQUEST. Used during endgame mode to suppress duplicate deliveries. |
| `0x07` | REJECT | Bidirectional | Refuse a message with an error code. Used for protocol violations, capacity limits, and invalid requests. |
| `0x08` | KEEP_ALIVE | Bidirectional | Indicate the peer is still active. Carries no body. Sent when no other message has been sent within the keep-alive interval. |

Type values `0x00` and `0x09`–`0x7F` are reserved for future Tessera protocol use. Values `0x80`–`0xFF` are reserved for extension messages (see section 8).

### Message lifecycle

A well-formed peer session follows this sequence:

```
Initiator                          Responder
    │                                  │
    │──── HANDSHAKE ──────────────────►│
    │◄─── HANDSHAKE ──────────────────│
    │                                  │
    │──── BITFIELD ───────────────────►│
    │◄─── BITFIELD ───────────────────│
    │                                  │
    │  ┌── transfer phase ──────────┐  │
    │  │  REQUEST / PIECE / HAVE    │  │
    │  │  CANCEL / REJECT           │  │
    │  │  KEEP_ALIVE                │  │
    │  └────────────────────────────┘  │
    │                                  │
    │  (channel close via MFP)         │
    │                                  │
```

**State machine rules:**

1. The first message on any channel **must** be HANDSHAKE. Any other message type received before a completed handshake triggers a REJECT with code `UNEXPECTED_MSG` and channel closure.
2. After both peers have exchanged HANDSHAKE, each peer **must** send exactly one BITFIELD. No REQUEST, PIECE, or HAVE may be sent before both bitfields are exchanged.
3. Once bitfields are exchanged, the channel enters the **transfer phase**. REQUEST, PIECE, HAVE, CANCEL, REJECT, and KEEP_ALIVE may be sent in any order.
4. A second HANDSHAKE or BITFIELD on an already-established channel triggers a REJECT with code `DUPLICATE_MSG`.

### Message descriptions

**HANDSHAKE** — Establishes the shared context for the channel. Both peers must agree on the manifest hash; a mismatch means they are not in the same swarm, and the channel is closed. The protocol version field allows peers to detect incompatible implementations early.

**BITFIELD** — A compact representation of the sender's tessera inventory. Each bit at position *i* indicates whether the sender holds tessera *i*. The bitfield length is derived from the manifest's tessera count (exchanged or known via the manifest). A seeder sends an all-ones bitfield; a fresh leecher sends all-zeros.

**REQUEST** — Asks the peer to send one or more tesserae. Each request specifies a tessera index. The Request Scheduler (ts-spec-004) decides which indices to request and from which peers. A peer may have multiple outstanding requests on the same channel, bounded by the configured concurrency limit.

**PIECE** — Carries the raw bytes of a single tessera along with its index. The receiver hashes the payload and verifies it against the manifest's hash tree (Piece Verifier, ts-spec-004). On mismatch, the receiver sends a REJECT with code `HASH_MISMATCH` and scores the peer down.

**HAVE** — A lightweight announcement that the sender now holds a tessera it previously did not. Sent immediately after a tessera is verified and written to disk. Peers update their internal view of the sender's bitfield accordingly.

**CANCEL** — Withdraws a previously issued REQUEST. Primarily used in endgame mode, where the same tessera is requested from multiple peers. Once any peer delivers it, the fetcher cancels the redundant requests to avoid wasting bandwidth.

**REJECT** — A structured error response. Carries an error code and the `msg_type` of the rejected message. May optionally include the request context (e.g., the tessera index that was refused). See section 7 for the full error code catalog.

**KEEP_ALIVE** — A zero-body heartbeat. Prevents MFP from treating an idle channel as dead. The keep-alive interval is configurable (ts-spec-010); the default is 30 seconds.

## 4. Message Encoding

All Tessera messages use a binary encoding with big-endian byte order. No self-describing serialization framework (protobuf, msgpack, JSON) is used — the format is hand-specified for compactness and zero-copy parsing.

### Common header

Every Tessera message begins with a 1-byte type tag:

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type
1       ...   message body (type-specific)
```

### Field type conventions

| Notation | Meaning |
|----------|---------|
| `u8` | Unsigned 8-bit integer |
| `u16` | Unsigned 16-bit integer, big-endian |
| `u32` | Unsigned 32-bit integer, big-endian |
| `u64` | Unsigned 64-bit integer, big-endian |
| `bytes(n)` | Fixed-length byte sequence of exactly *n* bytes |
| `bytes(*)` | Variable-length byte sequence consuming all remaining bytes in the message |
| `bits(n)` | Bitfield of *n* bits, padded to the next byte boundary with trailing zeros |

### Per-type layouts

#### HANDSHAKE (0x01)

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type        = 0x01
1       2     version         Protocol version (currently 0x0001)
3       32    manifest_hash   SHA-256 hash of the manifest this peer wants to exchange
35      4     tessera_count   Total number of tesserae in the mosaic (u32)
39      4     tessera_size    Default tessera size in bytes (u32)
```

Total: 43 bytes (fixed).

The `tessera_count` and `tessera_size` fields allow the receiver to validate the subsequent BITFIELD length and to sanity-check incoming PIECE payloads before obtaining the full manifest. The final tessera may be smaller than `tessera_size` — this is implicit and does not require a separate field.

#### BITFIELD (0x02)

```
Offset  Size         Field
──────  ────         ─────
0       1            msg_type    = 0x02
1       ⌈count/8⌉   bitfield    One bit per tessera, MSB-first, trailing bits zero-padded
```

Total: 1 + ⌈tessera_count / 8⌉ bytes.

Bit *i* (counting from 0, MSB of first byte = index 0) is `1` if the sender holds tessera *i*, `0` otherwise. For a mosaic with 1000 tesserae, the bitfield is 125 bytes. For a 4 GB file at 256 KB tessera size (16,384 tesserae), the bitfield is 2,048 bytes — well within MFP's payload limit.

#### REQUEST (0x03)

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type        = 0x03
1       4     index           Tessera index being requested (u32)
```

Total: 5 bytes (fixed).

One REQUEST message per tessera. Batching multiple indices into a single message was considered and rejected — individual messages simplify cancellation (one CANCEL per REQUEST) and allow MFP's per-message ordering to naturally sequence requests.

#### PIECE (0x04)

```
Offset  Size      Field
──────  ────      ─────
0       1         msg_type    = 0x04
1       4         index       Tessera index (u32)
5       bytes(*)  data        Raw tessera bytes
```

Total: 5 + tessera_data_length bytes.

The receiver knows the expected length from the manifest (all tesserae are `tessera_size` except potentially the last). The hash is not included in the message — the receiver computes SHA-256 over `data` and verifies against the manifest's hash tree independently. Including the hash would let a poisoner pre-compute a "matching" pair; omitting it forces verification against the trusted manifest.

#### HAVE (0x05)

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type    = 0x05
1       4     index       Tessera index now held (u32)
```

Total: 5 bytes (fixed).

#### CANCEL (0x06)

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type    = 0x06
1       4     index       Tessera index to cancel (u32)
```

Total: 5 bytes (fixed).

A CANCEL for an index that was never requested or has already been served is silently ignored — it is not an error.

#### REJECT (0x07)

```
Offset  Size   Field
──────  ────   ─────
0       1      msg_type         = 0x07
1       1      rejected_type    msg_type of the message being rejected
2       2      error_code       Error code (u16, see section 7)
4       4      context          Optional context (u32). For REQUEST/PIECE rejections, this is the tessera index. Zero if not applicable.
```

Total: 8 bytes (fixed).

#### KEEP_ALIVE (0x08)

```
Offset  Size  Field
──────  ────  ─────
0       1     msg_type    = 0x08
```

Total: 1 byte (fixed). No body.

## 5. Message Flow Diagrams

This section illustrates the three primary interaction patterns between Tessera peers. Each diagram shows the Tessera-layer messages only — MFP framing, encryption, and channel bootstrap are implicit.

### 5.1 Swarm Join (Fetcher joins a Seeder)

```
Fetcher (F)                                     Seeder (S)
    │                                               │
    │  [MFP: establish_channel with S's AgentId]     │
    │                                               │
    │──── HANDSHAKE ───────────────────────────────►│
    │     version=1, manifest_hash=H,               │
    │     tessera_count=N, tessera_size=256KB        │
    │                                               │
    │◄─── HANDSHAKE ───────────────────────────────│
    │     version=1, manifest_hash=H,               │
    │     tessera_count=N, tessera_size=256KB        │
    │                                               │
    │  [Both peers verify manifest_hash match]       │
    │  [Mismatch → REJECT(MANIFEST_MISMATCH) + close]│
    │                                               │
    │──── BITFIELD ────────────────────────────────►│
    │     bits: 0000...0 (holds nothing)             │
    │                                               │
    │◄─── BITFIELD ────────────────────────────────│
    │     bits: 1111...1 (holds everything)          │
    │                                               │
    │  [Transfer phase begins]                       │
```

The initiator (fetcher) sends HANDSHAKE first. The responder (seeder) replies with its own HANDSHAKE. If the manifest hashes do not match, the responder sends REJECT with code `MANIFEST_MISMATCH` and closes the MFP channel. Both peers then exchange bitfields before any data transfer begins.

### 5.2 Piece Exchange (Steady State)

```
Fetcher (F)                                     Seeder (S)
    │                                               │
    │──── REQUEST(index=42) ───────────────────────►│
    │──── REQUEST(index=107) ──────────────────────►│
    │──── REQUEST(index=3) ────────────────────────►│
    │                                               │
    │◄─── PIECE(index=42, data=...) ───────────────│
    │                                               │
    │  [F: verify SHA-256 against hash tree]         │
    │  [F: write to disk, update bitfield]           │
    │                                               │
    │──── HAVE(index=42) ──────────────────────────►│
    │                                               │
    │◄─── PIECE(index=107, data=...) ──────────────│
    │                                               │
    │  [F: verify — MISMATCH]                        │
    │                                               │
    │──── REJECT(rejected_type=0x04,                │
    │           error_code=HASH_MISMATCH,           │
    │           context=107) ──────────────────────►│
    │                                               │
    │  [F: score S down, re-request 107 from        │
    │   another peer]                                │
    │                                               │
    │◄─── PIECE(index=3, data=...) ────────────────│
    │                                               │
    │  [F: verify — OK]                              │
    │                                               │
    │──── HAVE(index=3) ───────────────────────────►│
    │                                               │
```

The fetcher pipelines multiple REQUESTs without waiting for each PIECE. The seeder serves them in whatever order is efficient. The fetcher verifies each piece independently and broadcasts HAVE to all connected peers (not just the sender) upon success.

### 5.3 Endgame Mode

When the fetcher has only a few tesserae remaining, it enters endgame mode: the same tessera is requested from multiple peers to avoid slow completion caused by a single slow or unresponsive peer.

```
Fetcher (F)                  Peer A              Peer B
    │                           │                    │
    │  [3 tesserae remaining: 500, 501, 502]         │
    │                           │                    │
    │──── REQUEST(500) ────────►│                    │
    │──── REQUEST(500) ─────────────────────────────►│
    │──── REQUEST(501) ────────►│                    │
    │──── REQUEST(501) ─────────────────────────────►│
    │──── REQUEST(502) ────────►│                    │
    │──── REQUEST(502) ─────────────────────────────►│
    │                           │                    │
    │◄─── PIECE(500) ──────────│                    │
    │                           │                    │
    │  [F: verify — OK]         │                    │
    │                           │                    │
    │──── CANCEL(500) ──────────────────────────────►│
    │                           │                    │
    │◄─── PIECE(501) ───────────────────────────────│
    │                           │                    │
    │  [F: verify — OK]         │                    │
    │                           │                    │
    │──── CANCEL(501) ─────────►│                    │
    │                           │                    │
    │◄─── PIECE(502) ──────────│                    │
    │                           │                    │
    │  [F: verify — OK, mosaic complete]             │
    │                           │                    │
    │──── CANCEL(502) ──────────────────────────────►│
    │                           │                    │
```

When a tessera arrives from one peer, the fetcher sends CANCEL to all other peers that received a REQUEST for the same index. A PIECE arriving after a CANCEL is silently discarded (the tessera is already verified and written). The peer receiving a CANCEL after already sending the PIECE treats it as a no-op.

## 6. Payload Size Constraints

Tessera messages ride inside MFP payloads. MFP enforces size limits at the transport layer; Tessera must stay within those bounds and impose its own application-layer constraints.

### MFP limits

| Limit | Value | Source |
|-------|-------|--------|
| Default max payload | 1,048,576 bytes (1 MB) | `RuntimeConfig.max_payload_size` |
| Hard max payload | 10,485,760 bytes (10 MB) | `MAX_PAYLOAD_SIZE_BYTES` in MFP validation |
| Wire overhead per message | 64 + (2 × frame_depth × 16) bytes | Envelope header + frame open/close |

With the default frame depth of 4, wire overhead is 192 bytes per message. This overhead is MFP's concern — Tessera's payload budget is the full `max_payload_size`.

### Tessera size budget

The PIECE message is the only variable-length message that approaches the payload limit. Its on-wire size is:

```
piece_wire_size = 5 + tessera_data_length
```

The default tessera size of 256 KB (262,144 bytes) produces a PIECE payload of 262,149 bytes — comfortably within the 1 MB default. The relationship:

| Tessera size | PIECE payload | Fits in 1 MB default | Fits in 10 MB hard limit |
|-------------|--------------|---------------------|------------------------|
| 64 KB | 65,541 bytes | Yes | Yes |
| 256 KB (default) | 262,149 bytes | Yes | Yes |
| 512 KB | 524,293 bytes | Yes | Yes |
| 1 MB | 1,048,581 bytes | No (exceeds by 5 bytes) | Yes |
| 1 MB - 8 bytes | 1,048,568 bytes | Yes (tight fit) | Yes |

**Constraint:** `tessera_size` must satisfy `tessera_size + 5 ≤ max_payload_size`. At the default `max_payload_size` of 1 MB, the maximum tessera size is 1,048,571 bytes. Implementations should validate this at configuration time and reject configurations where the tessera size exceeds the MFP payload budget.

### Control message sizes

All non-PIECE messages are small and fixed-size:

| Message | Size | Notes |
|---------|------|-------|
| HANDSHAKE | 43 bytes | Largest fixed-size message |
| BITFIELD | 1 + ⌈N/8⌉ bytes | For N=16,384 (4 GB file): 2,049 bytes |
| REQUEST | 5 bytes | |
| HAVE | 5 bytes | |
| CANCEL | 5 bytes | |
| REJECT | 8 bytes | |
| KEEP_ALIVE | 1 byte | Smallest message |

None of these approach the payload limit under any realistic mosaic size. A BITFIELD for a 1 TB file at 256 KB tessera size would be ~512 KB — still within the 1 MB default.

### Manifest transfer

The manifest is not a Tessera wire message — it is exchanged as part of the swarm join process defined in ts-spec-007 (Swarm & Peer Discovery). However, the manifest must also fit within MFP's payload limit when transmitted over a channel. For extremely large mosaics, manifest size scales with tessera count (32 bytes per hash tree leaf). A 1 TB file at 256 KB tessera size has ~4 million tesserae, producing a hash tree of ~128 MB — far exceeding any single MFP message. The manifest transfer strategy (chunked manifest, out-of-band fetch, or pre-shared) is specified in ts-spec-006.

## 7. Error & Rejection Messages

REJECT messages carry a `u16` error code that identifies the reason for rejection. Error codes are grouped by range to separate protocol-level violations from application-level refusals.

### Error code registry

#### Protocol errors (0x0100–0x01FF)

Violations of the message format, state machine, or wire protocol rules defined in this spec.

| Code | Name | Meaning |
|------|------|---------|
| `0x0100` | `UNEXPECTED_MSG` | Message type is not valid in the current state (e.g., REQUEST before BITFIELD exchange is complete). |
| `0x0101` | `DUPLICATE_MSG` | A message that must be sent exactly once was sent again (e.g., a second HANDSHAKE). |
| `0x0102` | `MANIFEST_MISMATCH` | The peer's HANDSHAKE contains a manifest hash that does not match the local manifest hash. The peers are not in the same swarm. Channel should be closed. |
| `0x0103` | `VERSION_MISMATCH` | The peer's HANDSHAKE contains a protocol version that this implementation does not support. Channel should be closed. |
| `0x0104` | `MALFORMED_MSG` | The message body could not be parsed according to the layout for its declared `msg_type`. |
| `0x0105` | `UNKNOWN_MSG_TYPE` | The `msg_type` byte is not recognized. Applies to the `0x09`–`0x7F` reserved range and to extension types (`0x80`–`0xFF`) that the receiver does not implement. |

#### Transfer errors (0x0200–0x02FF)

Failures specific to tessera exchange during the transfer phase.

| Code | Name | Meaning |
|------|------|---------|
| `0x0200` | `INDEX_OUT_OF_RANGE` | The requested tessera index exceeds the mosaic's tessera count. |
| `0x0201` | `HASH_MISMATCH` | The received PIECE data does not match the expected hash in the manifest's hash tree. The sender served a corrupted or poisoned tessera. |
| `0x0202` | `NOT_AVAILABLE` | The peer does not hold the requested tessera. This can occur if a peer's bitfield was stale or if the peer has evicted tesserae from local storage. |
| `0x0203` | `ALREADY_HAVE` | The sender pushed an unsolicited PIECE for a tessera the receiver already holds. Not an error per se, but the receiver discards the data and informs the sender. |

#### Capacity errors (0x0300–0x03FF)

Refusals due to resource limits, not protocol violations.

| Code | Name | Meaning |
|------|------|---------|
| `0x0300` | `OVERLOADED` | The peer cannot serve more requests at this time. The requester should back off and retry later or try another peer. |
| `0x0301` | `SWARM_FULL` | The swarm has reached its maximum peer count. The joining peer should try again later or contact a different seeder. |
| `0x0302` | `SHUTTING_DOWN` | The peer is in graceful shutdown and will not accept new requests. Existing in-flight pieces may still be delivered. |

### Behavior on REJECT receipt

| Error range | Receiver action |
|------------|-----------------|
| Protocol errors (`0x01xx`) | Log the violation. For `MANIFEST_MISMATCH` and `VERSION_MISMATCH`, close the channel immediately. For others, close the channel if the violation suggests an incompatible or malicious peer. |
| Transfer errors (`0x02xx`) | For `HASH_MISMATCH`, score the sender down and re-request from another peer. For `NOT_AVAILABLE`, update the peer's bitfield and re-request from another peer. For `INDEX_OUT_OF_RANGE`, log as a local bug (the Request Scheduler issued a bad index). For `ALREADY_HAVE`, no action needed. |
| Capacity errors (`0x03xx`) | For `OVERLOADED`, apply exponential backoff before re-requesting from the same peer. For `SWARM_FULL`, try joining through a different peer or retry after a delay. For `SHUTTING_DOWN`, stop sending new requests to this peer; allow in-flight pieces to complete. |

### Unsolicited messages

A peer that receives a PIECE it did not request (outside endgame mode) sends REJECT with code `ALREADY_HAVE` if it holds the tessera, or silently discards it if it does not. Repeated unsolicited messages from the same peer contribute to a negative peer score (ts-spec-008).

## 8. Extensibility

The wire protocol is designed to accommodate new message types and protocol evolution without breaking existing peers.

### Extension message range

Type values `0x80`–`0xFF` (128 values) are reserved for extension messages. These are messages defined outside the core Tessera protocol — by plugins, experimental features, or future optional capabilities (e.g., AI-driven metadata exchange via the Intelligence Bridge).

Extension messages follow the same encoding rules as core messages: 1-byte `msg_type` at offset 0, followed by a type-specific body. The only difference is how unrecognized types are handled.

### Unknown type handling

A peer that receives a message with an unrecognized `msg_type` **must** respond according to the type range:

| Range | Behavior |
|-------|----------|
| `0x00` | Reserved. REJECT with `UNKNOWN_MSG_TYPE`. |
| `0x01`–`0x08` | Core types. Must be implemented by all peers. |
| `0x09`–`0x7F` | Reserved for future core types. REJECT with `UNKNOWN_MSG_TYPE`. |
| `0x80`–`0xFF` | Extension types. Silently ignore if not recognized. Do **not** send REJECT — the sender knows the extension is optional. |

This split ensures that core protocol messages are always understood (a peer that cannot parse a core type is broken), while extension messages degrade gracefully (a peer without a particular extension simply ignores those messages).

### Protocol version negotiation

The HANDSHAKE message carries a `version` field (currently `0x0001`). Version semantics:

- **Minor changes** (new extension messages, new optional fields appended to existing messages) do not increment the version. Forward-compatible peers silently ignore unknown trailing bytes.
- **Breaking changes** (altered field layouts, removed message types, changed state machine rules) increment the version. A peer that receives a HANDSHAKE with an unsupported version sends REJECT with `VERSION_MISMATCH` and closes the channel.

A peer **must** support exactly one protocol version. There is no multi-version negotiation — the protocol is young enough that maintaining backward compatibility across breaking changes is not worth the complexity. If a breaking change is needed, all peers upgrade.

### Adding a new core message type

To add a new core message type (in the `0x09`–`0x7F` range):

1. Assign the next sequential `msg_type` value.
2. Define the field layout in this spec (section 4).
3. Define state machine rules — when in the session lifecycle this message may be sent (section 3).
4. Add error codes if the new message introduces new failure modes (section 7).
5. Increment the protocol version if the change is not backward-compatible.

### Adding an extension message type

To add an extension message type (in the `0x80`–`0xFF` range):

1. Choose any unused value in `0x80`–`0xFF`. No central registry is required — collision is managed by the deployer.
2. Define the field layout in the extension's own documentation, following the encoding conventions in section 4.
3. Extension messages may only be sent during the transfer phase (after HANDSHAKE and BITFIELD exchange).
4. The sender must tolerate the message being silently ignored by peers that do not implement the extension.

---

## 9. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Goals G1–G3 (authentication, encryption, anti-replay) that the wire protocol inherits from MFP |
| R2 | ts-spec-002 — Glossary | Defines tessera, mosaic, manifest, bitfield, and all terms used in this document |
| R3 | ts-spec-003 — Threat Model | Threats T1 (piece poisoning), T2 (manifest tampering), T5 (selective withholding), T10 (bandwidth exhaustion) addressed by wire-level message validation |
| R4 | ts-spec-004 — System Architecture | Transfer Engine components (Request Scheduler, Piece Verifier, Bitfield Manager) that produce and consume wire messages |
| R5 | MFP Python Implementation (mirror-frame-protocol) | Wire envelope format, AES-256-GCM encryption, `mfp_send()` API, payload size limits |
| R6 | ts-spec-006 — Content Addressing Spec | Manifest format, hash tree construction, and manifest transfer strategy |
| R7 | ts-spec-007 — Swarm & Peer Discovery | Swarm join process and discovery protocol that precedes channel establishment |
| R8 | ts-spec-008 — Piece Selection & Transfer Strategy | Request Scheduler algorithms, peer scoring, endgame mode thresholds |
| R9 | ts-spec-010 — API & CLI Design | `TesseraConfig` defaults for tessera size, keep-alive interval, concurrency limits |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
