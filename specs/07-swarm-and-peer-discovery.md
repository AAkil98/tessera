# Swarm & Peer Discovery

```yaml
id: ts-spec-007
type: spec
status: stable
created: 2026-03-15
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [swarm, discovery, peer-management, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Swarm Lifecycle
3. Peer Admission & Eviction
4. Discovery Backend Protocol
5. Default Discovery Backend
6. Multi-Source Verification
7. Capacity Enforcement
8. Network Partition & Reconnection
9. References

---

## 1. Purpose & Scope

This document specifies how Tessera peers form, manage, and dissolve swarms — and how they find each other in the first place. It covers the Swarm Manager's four subcomponents (Swarm Registry, Peer Connector, Discovery Client, Capacity Enforcer) defined in ts-spec-004 (section 3.2), detailing their internal logic and interactions.

### What this spec defines

- **Swarm lifecycle.** The states a swarm passes through from creation (publisher announces) to teardown (last peer leaves), including draining behavior during graceful shutdown.
- **Peer admission and eviction.** How a peer joins a swarm (channel establishment, handshake, manifest exchange, bitfield swap), and when a peer is disconnected (scoring thresholds, protocol violations, capacity limits).
- **Discovery backend protocol.** The `DiscoveryBackend` interface that all discovery implementations must satisfy — `announce()`, `lookup()`, `unannounce()` — and the contract each method must honor.
- **Default discovery backend.** The centralized tracker client that ships as the default implementation, including its announce/lookup wire interaction.
- **Multi-source verification.** How the Discovery Client cross-references results when multiple backends are active, implementing the T8 (discovery poisoning) mitigation from ts-spec-003.
- **Capacity enforcement.** How the Capacity Enforcer bounds resource consumption — maximum peers per swarm, maximum swarms per node — and the rejection behavior when limits are reached.
- **Network partition and reconnection.** How the Swarm Manager detects peer unavailability, attempts reconnection, and recovers swarm state after a network partition.

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Wire message format and state machine (HANDSHAKE, BITFIELD, etc.) | ts-spec-005 |
| Manifest format and verification | ts-spec-006 |
| Which tesserae to request from which peers | ts-spec-008 |
| AI-driven discovery (natural-language queries) | ts-spec-009 |
| Configuration defaults (max peers, timeouts) | ts-spec-010 |
| On-disk persistence of swarm state | ts-spec-011 |

### Relationship to prior specs

The Swarm Manager communicates laterally with the Transfer Engine (ts-spec-004, section 2): it tells the Transfer Engine which peers are available, and the Transfer Engine tells the Swarm Manager when a peer should be scored down or disconnected. The wire protocol (ts-spec-005) defines the messages exchanged during peer admission — this spec defines when and why those messages are sent. The threat model (ts-spec-003) assigns this spec responsibility for T4 (sybil flooding) and T8 (discovery poisoning) mitigations.

## 2. Swarm Lifecycle

A swarm is the set of peers participating in the transfer of a specific mosaic, identified by its manifest hash. Swarms are ephemeral — they exist as long as at least one peer is interested in the mosaic. The Swarm Registry tracks all active swarms on the local node.

### States

A swarm on a given node passes through four states:

```
  publish() or fetch()
         │
         ▼
    ┌─────────┐      peers connected      ┌─────────┐
    │ PENDING  │ ──────────────────────── ►│ ACTIVE  │
    └─────────┘                            └────┬────┘
                                                │
                                   shutdown or cancel
                                                │
                                           ┌────▼────┐
                                           │DRAINING │
                                           └────┬────┘
                                                │
                                    all channels closed
                                                │
                                           ┌────▼────┐
                                           │ CLOSED  │
                                           └─────────┘
```

| State | Description |
|-------|-------------|
| **PENDING** | The swarm entry has been created in the Swarm Registry and the node has announced to the discovery service, but no peer channels have been established yet. For a publisher, this begins when `publish()` completes chunking. For a fetcher, this begins when `fetch()` starts discovery lookup. |
| **ACTIVE** | At least one peer channel is established. Tessera exchange is in progress (fetcher) or the node is serving requests (seeder). The swarm remains ACTIVE as long as at least one channel is open and the node has not requested shutdown. |
| **DRAINING** | The node has initiated graceful shutdown or the user has cancelled the transfer. No new peer connections are accepted. Existing in-flight PIECE deliveries are allowed to complete. REJECT with `SHUTTING_DOWN` is sent in response to new REQUESTs. |
| **CLOSED** | All channels are closed, all in-flight operations have completed. The swarm entry is removed from the Swarm Registry. The node unannounces from the discovery service. |

### Swarm creation

**Publisher path:**

1. Chunker produces the manifest (ts-spec-006).
2. Swarm Registry creates a new entry: `manifest_hash → {state: PENDING, role: SEEDER, peers: []}`.
3. Discovery Client calls `announce(manifest_hash, agent_id)` on all active backends.
4. MFP agent is bound if not already bound (one agent per Tessera node, shared across swarms).
5. Swarm transitions to ACTIVE when the first fetcher establishes a channel.

**Fetcher path:**

1. Application Interface receives `fetch(manifest_hash)`.
2. Swarm Registry creates a new entry: `manifest_hash → {state: PENDING, role: LEECHER, peers: []}`.
3. Discovery Client calls `lookup(manifest_hash)` on all active backends.
4. Peer Connector begins establishing channels with discovered peers.
5. Swarm transitions to ACTIVE when the first channel completes the HANDSHAKE + BITFIELD exchange.

### Role transition

A leecher that completes the mosaic (all tesserae received and whole-file verified) transitions to seeder:

1. The Swarm Registry updates the role from `LEECHER` to `SEEDER`.
2. The node continues serving tesserae to other peers in the swarm.
3. Discovery Client re-announces with the updated role if the backend supports role differentiation.

The transition is local — no wire message is sent. Connected peers already know this node's bitfield (all-ones after completion).

### Swarm teardown

A swarm is torn down when:

- **Fetcher completes and does not want to seed.** The user or agent calls `cancel()` or the node's seeding policy (ts-spec-010) decides not to seed. The swarm transitions to DRAINING → CLOSED.
- **Publisher stops seeding.** The swarm transitions to DRAINING → CLOSED.
- **All peers disconnect.** The swarm remains in ACTIVE with zero peers. If no new peer connects within a configurable idle timeout, the swarm transitions to CLOSED.
- **Node shutdown.** All swarms transition to DRAINING simultaneously. The shutdown timeout (ts-spec-004, section 7) bounds total draining time.

## 3. Peer Admission & Eviction

The Peer Connector manages the lifecycle of individual peer connections within a swarm. Every connection passes through admission (channel establishment and handshake) and may end in eviction (voluntary or forced disconnection).

### Admission sequence

When a fetcher discovers a peer or a seeder receives an incoming channel request, the Peer Connector executes the following sequence:

```
Peer Connector                          Remote Peer
    │                                       │
    │  1. Check Capacity Enforcer           │
    │     (reject if swarm/node full)       │
    │                                       │
    │  2. establish_channel(peer_agent_id)   │
    │──── MFP channel bootstrap ───────────►│
    │                                       │
    │  3. HANDSHAKE exchange                │
    │──── ts-spec-005 state machine ───────►│
    │◄──────────────────────────────────────│
    │                                       │
    │  4. Manifest exchange (if needed)     │
    │     ts-spec-006, section 6            │
    │                                       │
    │  5. BITFIELD exchange                 │
    │──── ts-spec-005 state machine ───────►│
    │◄──────────────────────────────────────│
    │                                       │
    │  6. Register peer in Swarm Registry   │
    │  7. Notify Transfer Engine            │
    │                                       │
```

**Step details:**

1. **Capacity check.** Before allocating any resources, the Capacity Enforcer verifies that the swarm has not reached `max_peers_per_swarm` and the node has not reached `max_swarms_per_node`. If either limit is hit, the connection is rejected — for incoming connections, a REJECT with `SWARM_FULL` is sent after HANDSHAKE.

2. **Channel establishment.** The Peer Connector calls `handle.establish_channel(peer_agent_id)` to create an MFP bilateral channel. This performs the X25519 key exchange and establishes the encrypted pipe. If the channel cannot be established (peer unreachable, key exchange failure), the admission fails silently — the Peer Connector moves on to the next discovered peer.

3. **Handshake.** Both peers exchange HANDSHAKE messages (ts-spec-005, section 3). The Peer Connector verifies:
   - `manifest_hash` matches the local swarm's manifest hash. Mismatch → REJECT with `MANIFEST_MISMATCH`, close channel.
   - `version` is supported. Mismatch → REJECT with `VERSION_MISMATCH`, close channel.

4. **Manifest exchange.** If the fetcher does not yet have the manifest (signaled by `tessera_count = 0` in its HANDSHAKE), the seeder delivers it via the inline or chunked strategy defined in ts-spec-006, section 6. The fetcher verifies the manifest against the trusted manifest hash before proceeding.

5. **Bitfield exchange.** Both peers send their BITFIELD. The Peer Connector passes the remote peer's bitfield to the Bitfield Manager in the Transfer Engine.

6. **Registration.** The peer is added to the swarm's peer list in the Swarm Registry with initial metadata: `{agent_id, channel_id, role, bitfield, connected_at, score: 0.0}`.

7. **Notification.** The Transfer Engine is notified that a new peer is available. The Request Scheduler may immediately begin issuing REQUESTs if the peer holds needed tesserae.

### Admission failure handling

| Failure | Behavior |
|---------|----------|
| Capacity limit reached | REJECT with `SWARM_FULL`. Channel closed. Peer may retry later. |
| Channel establishment fails | Log and skip. Try next discovered peer. |
| HANDSHAKE manifest mismatch | REJECT with `MANIFEST_MISMATCH`. Channel closed. |
| HANDSHAKE version mismatch | REJECT with `VERSION_MISMATCH`. Channel closed. |
| Manifest verification fails | Channel closed. Try another peer for the manifest. |
| BITFIELD not received within timeout | Channel closed. Peer treated as unresponsive. |

### Eviction triggers

A peer is evicted (channel closed, removed from Swarm Registry) when any of the following occur:

| Trigger | Source | Behavior |
|---------|--------|----------|
| **Peer score below threshold** | Peer Scorer (ts-spec-008) | The peer's cumulative score (latency, failure rate, hash mismatches) falls below `min_peer_score`. The Swarm Manager closes the channel. |
| **Protocol violation** | Wire protocol state machine | Receiving an invalid message (UNEXPECTED_MSG, DUPLICATE_MSG, MALFORMED_MSG) that suggests an incompatible or malicious peer. Channel closed immediately. |
| **Repeated hash mismatches** | Piece Verifier | A peer that serves `max_hash_failures` poisoned tesserae within a sliding window is evicted and its AgentId is added to a per-swarm blocklist for the duration of the swarm. |
| **Channel closed by remote** | MFP channel status | The remote peer closed the channel or the MFP runtime reports the channel as CLOSED. The peer is removed from the registry. |
| **MFP quarantine** | MFP runtime | The peer's agent has been quarantined by MFP (rate limiting, validation failure). The channel becomes unusable. The peer is removed. |
| **Capacity rebalancing** | Capacity Enforcer | When a higher-scoring peer requests admission and the swarm is full, the lowest-scoring peer may be evicted to make room (only if its score is below `eviction_threshold`). |

### Per-swarm blocklist

When a peer is evicted for hash mismatches or repeated protocol violations, its AgentId is added to the swarm's blocklist. Blocklisted peers are rejected at step 1 of admission — before channel establishment — for the lifetime of the swarm. The blocklist is not persisted across swarm restarts and does not apply to other swarms.

## 4. Discovery Backend Protocol

The Discovery Client does not implement discovery logic directly. It delegates to one or more `DiscoveryBackend` implementations — pluggable components that know how to find peers for a given manifest hash. This section defines the interface that all backends must satisfy.

### Interface

```python
class DiscoveryBackend(Protocol):
    async def announce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
        role: Literal["seeder", "leecher"],
    ) -> None:
        """
        Register this peer as participating in the swarm for the given manifest.

        Called when a swarm is created (publish or fetch) and when a leecher
        transitions to seeder. Backends that do not support role differentiation
        may ignore the role parameter.

        Must be idempotent — calling announce twice with the same arguments
        has no additional effect.
        """
        ...

    async def lookup(
        self,
        manifest_hash: bytes,
    ) -> list[PeerRecord]:
        """
        Return a list of peers known to hold (or be fetching) the given manifest.

        Returns an empty list if no peers are found. Must not raise on
        "not found" — absence is a valid result.

        Results may be stale. The caller (Discovery Client) is responsible
        for verifying that returned peers are reachable and hold the
        correct manifest.
        """
        ...

    async def unannounce(
        self,
        manifest_hash: bytes,
        agent_id: bytes,
    ) -> None:
        """
        Remove this peer from the swarm listing for the given manifest.

        Called when a swarm transitions to CLOSED. Must be idempotent —
        unannouncing a peer that is not listed is a no-op.
        """
        ...
```

### PeerRecord

```python
@dataclass
class PeerRecord:
    agent_id: bytes          # 32-byte MFP AgentId
    role: str                # "seeder" or "leecher"
    last_seen: float         # Unix timestamp of last announce/refresh
    source: str              # Name of the backend that returned this record
```

The `source` field is set by the Discovery Client, not the backend itself. It identifies which backend produced the record — used for multi-source verification (section 6).

### Contract

All `DiscoveryBackend` implementations must honor the following:

| Rule | Rationale |
|------|-----------|
| All methods are async. | Discovery may involve network I/O (tracker queries, gossip rounds). The Swarm Manager runs on asyncio. |
| `announce` and `unannounce` are idempotent. | The Swarm Manager may retry on transient failure without side effects. |
| `lookup` never raises for "not found." | An empty list is the correct response. Exceptions are reserved for backend failures (network error, malformed response). |
| `lookup` results are best-effort. | Results may be stale, incomplete, or contain peers that are no longer reachable. The Peer Connector validates every returned peer during admission. |
| Backends must tolerate concurrent calls. | Multiple swarms may call `announce`, `lookup`, and `unannounce` concurrently from different asyncio tasks. |
| Backends must not block the event loop. | If the backend performs blocking I/O (e.g., a synchronous HTTP client), it must use `asyncio.to_thread()`. |

### Backend registration

The Discovery Client is configured with a list of backends at node startup via `TesseraConfig` (ts-spec-010). Backends are ordered — the first backend is the primary, subsequent backends are secondary. The order affects multi-source verification (section 6) but not `announce`/`unannounce`, which are called on all backends.

```python
config = TesseraConfig(
    discovery_backends=[
        TrackerBackend(url="https://tracker.example.com"),
        GossipBackend(seed_peers=[...]),
    ]
)
```

## 5. Default Discovery Backend

Tessera ships with a single built-in discovery backend: a centralized tracker client. It is the simplest backend that satisfies the `DiscoveryBackend` protocol and is sufficient for the target scale of tens-to-hundreds of peers (NG3).

### Architecture

The tracker is a lightweight HTTP service that maps manifest hashes to peer lists. It is **not** part of the Tessera node — it runs as a separate process or service. The `TrackerBackend` is the client-side component that communicates with the tracker over HTTPS.

```
Tessera Node A                    Tracker Service                  Tessera Node B
    │                                  │                                │
    │── POST /announce ───────────────►│                                │
    │   {manifest_hash, agent_id,      │                                │
    │    role: "seeder"}               │                                │
    │                                  │                                │
    │                                  │◄── POST /announce ────────────│
    │                                  │    {manifest_hash, agent_id,   │
    │                                  │     role: "leecher"}           │
    │                                  │                                │
    │                                  │◄── GET /lookup?hash=... ──────│
    │                                  │──── [{agent_id_A, "seeder"}] ►│
    │                                  │                                │
    │                     [Node B connects directly to Node A via MFP]  │
    │◄══════════════ MFP bilateral channel ════════════════════════════│
```

The tracker is a directory, not a relay. It never sees tessera data, manifests, or MFP messages. Its only job is to answer "which AgentIds are in the swarm for this manifest hash?"

### TrackerBackend implementation

```python
class TrackerBackend:
    def __init__(self, url: str, refresh_interval: float = 60.0):
        self.url = url
        self.refresh_interval = refresh_interval

    async def announce(self, manifest_hash, agent_id, role):
        # POST /announce
        # Body: {manifest_hash (hex), agent_id (hex), role}
        # Response: 200 OK or 409 Already Announced (idempotent)

    async def lookup(self, manifest_hash):
        # GET /lookup?hash={manifest_hash_hex}
        # Response: 200 with JSON array of PeerRecord-like objects
        # Response: 200 with empty array if no peers found

    async def unannounce(self, manifest_hash, agent_id):
        # POST /unannounce
        # Body: {manifest_hash (hex), agent_id (hex)}
        # Response: 200 OK or 404 Not Found (idempotent)
```

### Tracker API surface

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/announce` | POST | `{manifest_hash, agent_id, role}` | `200 OK` |
| `/lookup` | GET | `?hash={manifest_hash_hex}` | `200` with `[{agent_id, role, last_seen}]` |
| `/unannounce` | POST | `{manifest_hash, agent_id}` | `200 OK` |
| `/health` | GET | — | `200 OK` |

All request and response bodies are JSON. Manifest hashes and AgentIds are hex-encoded strings.

### Tracker responsibilities

| The tracker does | The tracker does not |
|-----------------|---------------------|
| Store manifest_hash → peer list mappings | Store or relay manifests, tesserae, or MFP messages |
| Expire stale announcements (peers that have not refreshed within TTL) | Authenticate peers — any peer with a valid AgentId can announce |
| Return peer lists for lookup queries | Verify that peers actually hold the claimed manifest |
| Serve as a single point of coordination | Participate in the swarm or transfer protocol |

### Announce refresh

The `TrackerBackend` periodically re-announces to prevent stale expiry. Every `refresh_interval` seconds (default 60), it re-sends `announce()` for all active swarms. The tracker treats each announce as a heartbeat — updating the `last_seen` timestamp. Peers that have not refreshed within the tracker's configured TTL (tracker-side setting, not specified by Tessera) are pruned from lookup results.

### Tracker as a single point of failure

The centralized tracker is a single point of failure for discovery — not for transfer. If the tracker is down:

- **Existing swarms continue.** Peers already connected via MFP channels are unaffected. Tessera exchange continues normally.
- **New fetchers cannot discover peers.** `lookup()` fails, and the fetcher cannot find seeders. The fetcher retries with exponential backoff.
- **New publishers cannot announce.** `announce()` fails, but the publisher holds the manifest and tesserae locally. It can re-announce when the tracker recovers.

For deployments that require higher discovery availability, operators should configure multiple backends (section 6) or implement a gossip-based backend.

## 6. Multi-Source Verification

When multiple discovery backends are configured, the Discovery Client cross-references their results to reduce the risk of discovery poisoning (T8 in ts-spec-003). A single compromised backend cannot unilaterally direct a fetcher into a hostile swarm.

### Lookup aggregation

When `lookup(manifest_hash)` is called, the Discovery Client queries all configured backends concurrently and merges the results:

```
Discovery Client
    │
    ├── lookup() ──► Backend A ──► [peer1, peer2, peer3]
    │
    ├── lookup() ──► Backend B ──► [peer1, peer3, peer4]
    │
    └── lookup() ──► Backend C ──► [peer2, peer3, peer5]

    Merged: peer1(A,B)  peer2(A,C)  peer3(A,B,C)  peer4(B)  peer5(C)
```

Each peer in the merged result carries the set of backends that returned it (the `source` field in `PeerRecord`).

### Trust scoring

Peers are ranked by the number of backends that independently corroborate their presence:

| Corroboration | Trust level | Behavior |
|--------------|-------------|----------|
| Returned by all backends | **High** | Connected first. No additional verification needed beyond the standard HANDSHAKE. |
| Returned by majority of backends | **Medium** | Connected after high-trust peers. Standard admission sequence. |
| Returned by a single backend | **Low** | Connected last. Subject to stricter initial scrutiny — the Peer Connector applies a shorter HANDSHAKE timeout and the Peer Scorer starts the peer at a lower initial score. |

### Connection ordering

The Peer Connector processes discovered peers in trust-score order:

1. **High-trust peers** — connected first, up to `max_peers_per_swarm`.
2. **Medium-trust peers** — connected if capacity remains.
3. **Low-trust peers** — connected only if insufficient high/medium-trust peers are available.

Within the same trust level, peers are ordered by role (seeders before leechers) and then by `last_seen` (most recently seen first).

### Single-backend mode

When only one backend is configured (the common case with the default `TrackerBackend`), multi-source verification is not possible. All peers are treated as medium-trust. The T8 mitigation in this mode relies entirely on the HANDSHAKE manifest hash check — a peer returned by a compromised tracker that does not hold the correct manifest is rejected at admission step 3.

### Backend failure handling

| Scenario | Behavior |
|----------|----------|
| One backend fails, others succeed | Proceed with results from successful backends. Log the failure. Failed backend's results are treated as "empty" — peers only returned by the failed backend are not penalized. |
| All backends fail | `lookup()` returns an empty list. The fetcher retries with exponential backoff. |
| One backend is slow | The Discovery Client imposes a per-backend timeout (configurable, default 10 seconds). Results from backends that respond within the timeout are merged; slow backends are treated as failed for that lookup round. |

### Announce and unannounce

Unlike `lookup`, `announce` and `unannounce` are **not** cross-referenced — they are broadcast to all backends unconditionally. If one backend fails to receive an announce, the peer is still discoverable via the others. If one backend fails to receive an unannounce, it will eventually expire the stale entry via its TTL.

## 7. Capacity Enforcement

The Capacity Enforcer prevents resource exhaustion by bounding the number of peers per swarm and the number of active swarms per node. Without these limits, a sybil attacker (AC3) or a burst of legitimate fetchers could consume all available channels, memory, and bandwidth.

### Limits

| Limit | Scope | Default | Configurable via |
|-------|-------|---------|-----------------|
| `max_peers_per_swarm` | Per swarm | 50 | `TesseraConfig` (ts-spec-010) |
| `max_swarms_per_node` | Per node | 10 | `TesseraConfig` (ts-spec-010) |
| `max_channels_per_agent` | Per MFP agent | Inherited from MFP `RuntimeConfig` | MFP configuration |

The effective per-node channel limit is `min(max_peers_per_swarm × active_swarms, max_channels_per_agent)`. If MFP's channel limit is lower than Tessera's, MFP's limit governs — channel establishment will fail at the MFP layer before Tessera's limits are reached.

### Enforcement points

| Event | Check | Rejection |
|-------|-------|-----------|
| **Incoming channel request** | `swarm.peer_count < max_peers_per_swarm` | REJECT with `SWARM_FULL` after HANDSHAKE. Channel closed. |
| **Outgoing connection attempt** | `swarm.peer_count < max_peers_per_swarm` | Connection not attempted. Peer skipped, tried later if capacity frees. |
| **New swarm creation** (publish or fetch) | `node.swarm_count < max_swarms_per_node` | `publish()` or `fetch()` raises an error. The caller must wait for an existing swarm to close. |

### Capacity rebalancing

When a swarm is full and a new peer requests admission, the Capacity Enforcer may evict the lowest-scoring existing peer to make room — but only if:

1. The new peer's discovery trust level (section 6) is higher than the existing peer's current score, **and**
2. The existing peer's score is below `eviction_threshold` (a configurable value, default 0.2 on a 0.0–1.0 scale).

This prevents a well-behaved peer from being displaced by every new arrival while still allowing the swarm to improve its peer quality over time. If neither condition is met, the new peer receives REJECT with `SWARM_FULL`.

### Interaction with MFP limits

MFP imposes its own resource limits:

| MFP limit | Effect on Tessera |
|-----------|------------------|
| `max_agents` | Tessera uses one agent per node. This limit is not relevant unless the node runs other MFP applications concurrently. |
| `max_channels_per_agent` | Hard cap on total peer connections across all swarms. If reached, `establish_channel()` fails and the Peer Connector treats it as a capacity rejection. |
| `max_message_rate` | Peers that exceed MFP's rate limit are quarantined automatically. Tessera detects this via channel status and evicts the quarantined peer. |

### Monitoring

The Capacity Enforcer exposes the following to the Application Interface (ts-spec-010):

- Per-swarm: current peer count, capacity remaining, number of rejected admissions.
- Per-node: active swarm count, total channel count, capacity remaining.

These values are available through `status()` for human operators and agent callers.

## 8. Network Partition & Reconnection

Networks fail. Peers disappear without sending SHUTTING_DOWN. Channels drop silently. This section specifies how the Swarm Manager detects, responds to, and recovers from peer unavailability and network partitions.

### Detection

Peer unavailability is detected through three mechanisms:

| Mechanism | Detection time | Source |
|-----------|---------------|--------|
| **MFP channel closure** | Immediate | MFP runtime reports channel status as CLOSED. Triggered by TCP connection drop, remote process crash, or explicit close. |
| **KEEP_ALIVE timeout** | `2 × keep_alive_interval` (default 60s) | If no message of any type (including KEEP_ALIVE) is received from a peer within the timeout window, the peer is presumed dead. |
| **Request timeout** | Configurable per-request (default 30s) | A REQUEST that receives no PIECE or REJECT within the timeout contributes to the peer's failure rate. After `max_consecutive_timeouts` (default 3), the peer is presumed unavailable. |

The three mechanisms cover different failure modes: hard disconnects (MFP closure), silent disappearance (KEEP_ALIVE), and degraded responsiveness (request timeout).

### Response

When a peer is detected as unavailable:

1. **Remove from Swarm Registry.** The peer's entry is deleted. Its channel is closed if not already.
2. **Reclaim in-flight requests.** Any REQUESTs sent to the unavailable peer that have not been answered are returned to the Request Scheduler's pending queue. The scheduler re-issues them to other available peers.
3. **Update bitfield availability.** The Bitfield Manager recalculates tessera availability across remaining peers. If tesserae that were only available from the lost peer are now unavailable from any connected peer, the Discovery Client is triggered to find new peers (step 5).
4. **Update peer scores.** The Peer Scorer records the disconnection. Peers that disconnect cleanly (SHUTTING_DOWN received) are not penalized. Peers that disappear silently receive a score penalty.
5. **Re-discover if needed.** If the swarm's peer count falls below `min_peers_threshold` (default 2) or if needed tesserae are no longer available from any connected peer, the Discovery Client re-runs `lookup()` to find additional peers.

### Reconnection strategy

The Swarm Manager does not attempt to reconnect to a specific peer that has disconnected. Instead, it relies on discovery to find peers — which may include the previously disconnected peer if it has recovered and re-announced.

Rationale: MFP channels are stateful (ratchet position, key material). A dropped channel cannot be resumed — a new channel must be established from scratch. Since the new channel requires a full admission sequence (HANDSHAKE, manifest exchange, BITFIELD), there is no advantage to targeting a specific peer over discovering any available peer.

### Partition recovery

A network partition splits the swarm into isolated subgroups. From each subgroup's perspective, the peers in other subgroups have simply become unavailable. The response is the same as individual peer loss:

1. Unavailable peers are removed from the Swarm Registry.
2. In-flight requests are reclaimed.
3. Discovery is re-triggered if the remaining peer count is insufficient.

When the partition heals:

- Peers that re-announce to the discovery service become discoverable again.
- New channels are established through the normal admission sequence.
- Bitfields are exchanged fresh — no assumption is made about what the peer held before the partition.
- Transfer resumes from where each peer left off. The Request Scheduler sees new peers with new bitfields and incorporates them into its selection strategy.

### Swarm starvation

If all peers become unavailable and discovery returns no new peers, the swarm enters **starvation**:

1. The swarm remains in ACTIVE state with zero peers.
2. The Discovery Client retries `lookup()` with exponential backoff: 5s, 10s, 20s, 40s, up to a maximum interval of 5 minutes.
3. If no peers are found within `starvation_timeout` (configurable, default 30 minutes), the swarm transitions to CLOSED and `fetch()` returns an error indicating the mosaic is currently unavailable.
4. The incomplete mosaic's state (received tesserae, bitfield) is preserved on disk (ts-spec-011). A subsequent `fetch()` call with the same manifest hash can resume from where the previous attempt left off.

### Transfer resumption

When a fetcher reconnects to a swarm (either after partition recovery or after a fresh `fetch()` call for a partially-downloaded mosaic):

- The local bitfield reflects tesserae already verified and written to disk.
- The BITFIELD sent during admission accurately represents current holdings.
- The Request Scheduler only requests tesserae the fetcher does not yet hold.
- No tessera is re-downloaded unless whole-file verification (ts-spec-006, section 7) detects post-write corruption.

---

## 9. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Goal G1 (authenticated swarm), G4 (decentralized transfer), non-goal NG3 (target scale: tens-to-hundreds of peers) |
| R2 | ts-spec-002 — Glossary | Defines swarm, seeder, leecher, publisher, manifest hash, Discovery Client, Swarm Registry, Peer Connector, Capacity Enforcer |
| R3 | ts-spec-003 — Threat Model | T4 (sybil flooding) mitigated by capacity enforcement; T8 (discovery poisoning) mitigated by multi-source verification |
| R4 | ts-spec-004 — System Architecture | Swarm Manager component definitions (section 3.2), lateral communication with Transfer Engine (section 2), per-swarm asyncio tasks (section 7), forward dependency for network partition handling |
| R5 | ts-spec-005 — Wire Protocol Addendum | HANDSHAKE, BITFIELD state machine (section 3), REJECT error codes SWARM_FULL and SHUTTING_DOWN (section 7), KEEP_ALIVE interval (section 3) |
| R6 | ts-spec-006 — Content Addressing Spec | Manifest transfer strategies (section 6) used during peer admission |
| R7 | ts-spec-008 — Piece Selection & Transfer Strategy | Peer Scorer metrics and thresholds that drive eviction decisions |
| R8 | ts-spec-009 — AI Integration Spec | AI-driven discovery via Intelligence Bridge |
| R9 | ts-spec-010 — API & CLI Design | TesseraConfig defaults for max_peers_per_swarm, max_swarms_per_node, timeouts, starvation_timeout |
| R10 | ts-spec-011 — Storage & State Management | On-disk persistence of incomplete mosaic state for transfer resumption |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
