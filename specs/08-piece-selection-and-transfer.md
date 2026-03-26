# Piece Selection & Transfer Strategy

```yaml
id: ts-spec-008
type: spec
status: stable
created: 2026-03-16
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [transfer, piece-selection, peer-scoring, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Piece Selection Algorithms
3. Peer Selection
4. Peer Scoring
5. Request Pipeline
6. Endgame Mode
7. Transfer Metrics & Progress
8. References

---

## 1. Purpose & Scope

This document specifies how Tessera decides **what** to download and **from whom** — the Request Scheduler and Peer Scorer components defined in ts-spec-004 (section 3.1). These two components sit at the heart of transfer performance: good selection minimizes completion time, good scoring isolates bad peers.

### What this spec defines

- **Piece selection algorithms.** The strategies the Request Scheduler uses to choose which tesserae to request next — rarest-first as the default, with the `SelectionStrategy` extension point for alternatives including AI-driven selection.
- **Peer selection.** How the Request Scheduler chooses which peer to request a specific tessera from, based on peer scores and bitfield availability.
- **Peer scoring.** The metrics the Peer Scorer tracks (serve latency, failure rate, bytes delivered, hash mismatches), how they combine into a single score, and the thresholds that trigger deprioritization and eviction.
- **Request pipeline.** Concurrency control — how many requests can be in-flight per peer and per swarm, how timeouts are handled, and how failed requests are retried.
- **Endgame mode.** The transition from normal selection to aggressive duplicate requesting when the mosaic is nearly complete.
- **Transfer metrics.** How progress, throughput, and estimated completion time are computed and exposed to the Application Interface.

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Wire format for REQUEST, PIECE, CANCEL, REJECT | ts-spec-005 |
| Hash verification of received tesserae | ts-spec-006 |
| Peer admission, eviction, and discovery | ts-spec-007 |
| AI-driven selection and ranking logic | ts-spec-009 |
| Configuration defaults for concurrency and thresholds | ts-spec-010 |

### Relationship to prior specs

The Request Scheduler consumes bitfield state from the Bitfield Manager and peer scores from the Peer Scorer — both Transfer Engine components (ts-spec-004, section 3.1). It emits REQUEST messages (ts-spec-005) and receives PIECE/REJECT responses. When a peer's score drops below threshold, the Peer Scorer notifies the Swarm Manager (ts-spec-007) to trigger eviction. The Intelligence Bridge (ts-spec-004, section 3.3) can inject hints at the piece selection and peer selection stages when madakit is active.

## 2. Piece Selection Algorithms

Piece selection determines which tesserae the Request Scheduler requests next. The choice of algorithm directly affects swarm health — poor selection leads to common pieces being replicated while rare pieces become bottlenecks.

### Default: Rarest-first

The default algorithm prioritizes tesserae held by the fewest peers in the swarm. This is the same strategy used by BitTorrent, adapted for Tessera's semantics.

**Algorithm:**

1. For each tessera index *i* not yet held locally:
   - Count the number of connected peers whose bitfield has bit *i* set. This is the tessera's **availability count**.
2. Sort needed tesserae by availability count, ascending. Lowest availability = rarest = highest priority.
3. Break ties by index order (lower index first). This produces a deterministic, reproducible order when multiple tesserae have the same availability.
4. Return the top *k* tesserae, where *k* is the number of request slots available (section 5).

**Why rarest-first works:**

- **Prevents single-piece bottlenecks.** If only one seeder holds tessera 47 and it goes offline, no one in the swarm can complete the mosaic. Fetching rare pieces early distributes them across the swarm before the sole source disappears.
- **Improves swarm-wide availability.** As leechers acquire rare pieces and broadcast HAVE, those pieces become less rare. The swarm converges toward uniform availability.
- **Self-balancing.** Pieces that many peers already hold are naturally deprioritized, reducing redundant traffic.

### Sequential mode

In certain scenarios, rarest-first is suboptimal:

| Scenario | Why sequential is better |
|----------|------------------------|
| **Single seeder, single leecher** | No rarity differentiation exists — all pieces have availability 1. Sequential avoids the overhead of sorting. |
| **Resuming a partial download** | When most pieces are already held, fetching the remaining gaps in order maximizes disk write locality. |

The Request Scheduler automatically falls back to sequential (index-order) selection when:
- The swarm has only one connected peer, **or**
- Fewer than `sequential_threshold` tesserae remain (default: 5% of total tessera count, minimum 10).

### Random-first piece

On initial connection to a swarm, before the fetcher has received enough HAVE messages to build accurate availability counts, rarest-first has insufficient data. For the first `initial_random_count` requests (default: 4), the Request Scheduler selects tesserae at random from the set of pieces available from connected peers. This bootstraps diversity — the leecher quickly has something to share via HAVE announcements, making it a useful participant in the swarm.

After the initial random phase, the scheduler switches to rarest-first with accumulated availability data.

### SelectionStrategy extension point

The Request Scheduler accepts an optional `SelectionStrategy` protocol (ts-spec-004, section 8):

```python
class SelectionStrategy(Protocol):
    def select(
        self,
        needed: set[int],
        availability: dict[int, int],
        peer_bitfields: dict[bytes, set[int]],
        count: int,
    ) -> list[int]:
        """
        Return up to `count` tessera indices to request next.

        Args:
            needed: Indices of tesserae not yet held locally.
            availability: Map of tessera index → number of peers holding it.
            peer_bitfields: Map of peer AgentId → set of tessera indices held.
            count: Maximum number of indices to return.

        Returns:
            Ordered list of tessera indices, highest priority first.
        """
        ...
```

The default implementation is `RarestFirstStrategy`. The Intelligence Bridge (ts-spec-009) may provide an AI-driven strategy that considers file structure, content priority, or user intent.

## 3. Peer Selection

Once the Request Scheduler has chosen which tesserae to request, it must decide which peer to request each tessera from. Peer selection balances three concerns: speed (prefer fast peers), diversity (spread load across the swarm), and availability (only request from peers that hold the piece).

### Algorithm

For each tessera index *i* selected by the piece selection algorithm:

1. **Filter.** Identify the set of connected peers whose bitfield includes tessera *i*. Exclude peers that:
   - Already have an in-flight REQUEST for tessera *i* from this node (no duplicate requests outside endgame mode).
   - Have reached their per-peer in-flight request limit (`max_requests_per_peer`, section 5).
   - Are in DRAINING state (sent SHUTTING_DOWN).

2. **Rank.** Sort eligible peers by score (Peer Scorer, section 4), descending. Highest score = best peer.

3. **Select.** Choose the highest-ranked peer. If multiple peers share the top score, select the one with the fewest in-flight requests (load balancing).

4. **Issue.** Send REQUEST(index=*i*) to the selected peer. Record the request in the in-flight tracker.

### Load balancing

Strict best-score-first would funnel all requests to the single fastest peer, exhausting its capacity while other peers sit idle. The scheduler mitigates this by factoring in current load:

```
effective_score(peer) = peer.score × (1 - peer.in_flight / max_requests_per_peer)
```

A peer at half capacity retains its full score advantage. A peer near its request limit is deprioritized. This naturally spreads requests across peers while still preferring higher-quality ones.

### AI-driven peer ranking

When the Intelligence Bridge is active (ts-spec-009), it may provide a `PeerRankingHint` — a reordering of the peer list for a specific request. The hint is advisory:

- If the hint ranks a peer that passes the filter step, the scheduler uses the hint's ordering.
- If the hint includes a peer that fails the filter (at capacity, doesn't hold the piece), that entry is silently dropped.
- If no hint is provided, the default score-based ranking is used.

This allows an LLM to factor in contextual knowledge (e.g., preferring peers geographically closer, or peers that have historically served related content) without bypassing the scheduler's safety checks.

### No-peer scenario

If no eligible peer holds a needed tessera (all holders are at capacity, disconnected, or blocklisted), the tessera is placed in the **backlog** — a queue of indices that could not be scheduled. The backlog is re-evaluated whenever:

- A peer's in-flight count decreases (a PIECE or REJECT is received).
- A new peer joins the swarm.
- A connected peer sends HAVE for a backlogged index.

## 4. Peer Scoring

The Peer Scorer maintains a real-time quality score for every connected peer. Scores drive three decisions: peer selection (section 3), eviction (ts-spec-007, section 3), and capacity rebalancing (ts-spec-007, section 7).

### Metrics

The Peer Scorer tracks four metrics per peer, updated inline on each message exchange:

| Metric | Type | Updated on | Description |
|--------|------|-----------|-------------|
| `latency_ms` | Exponential moving average | Each PIECE received | Round-trip time from REQUEST sent to PIECE received. Measured per-request, smoothed with decay factor α = 0.3. |
| `failure_rate` | Ratio (0.0–1.0) | Each PIECE or REJECT received | `failures / total_responses` over a sliding window of the last `scoring_window` responses (default: 20). Failures include: REJECT with `NOT_AVAILABLE`, request timeouts, and hash mismatches. |
| `bytes_delivered` | Cumulative counter | Each verified PIECE | Total bytes of verified tessera data received from this peer. Not decayed — reflects lifetime contribution. |
| `hash_mismatches` | Counter | Each HASH_MISMATCH REJECT sent | Number of poisoned tesserae received from this peer. Not windowed — every mismatch is permanent. |

### Scoring function

The four metrics combine into a single score on a 0.0–1.0 scale:

```
score = w_latency × latency_score
      + w_failure × failure_score
      + w_throughput × throughput_score
      - penalty_per_mismatch × hash_mismatches
```

Where:

| Component | Computation | Weight (default) |
|-----------|------------|-----------------|
| `latency_score` | `1.0 - clamp(latency_ms / max_acceptable_latency, 0.0, 1.0)` | `w_latency = 0.3` |
| `failure_score` | `1.0 - failure_rate` | `w_failure = 0.4` |
| `throughput_score` | `clamp(bytes_delivered / throughput_baseline, 0.0, 1.0)` | `w_throughput = 0.3` |
| Hash mismatch penalty | Fixed penalty per mismatch | `penalty_per_mismatch = 0.25` |

Default constants:

| Constant | Default | Description |
|----------|---------|-------------|
| `max_acceptable_latency` | 5000 ms | Latency at or above this yields latency_score = 0. |
| `throughput_baseline` | 10 MB | Bytes delivered at or above this yields throughput_score = 1.0. |
| `scoring_window` | 20 | Number of recent responses used for failure_rate. |

The score is clamped to `[0.0, 1.0]` after computation.

### ScoringFunction extension point

The default scoring function can be replaced via the `ScoringFunction` callable (ts-spec-004, section 8):

```python
ScoringFunction = Callable[[PeerMetrics], float]
```

Where `PeerMetrics` is a dataclass exposing `latency_ms`, `failure_rate`, `bytes_delivered`, and `hash_mismatches`. Custom scoring functions must return a value in `[0.0, 1.0]`.

### Thresholds

| Threshold | Default | Effect |
|-----------|---------|--------|
| `min_peer_score` | 0.1 | Peers scoring below this are evicted (ts-spec-007, section 3). |
| `eviction_threshold` | 0.2 | Peers scoring below this may be displaced by higher-quality newcomers during capacity rebalancing. |
| `deprioritization_threshold` | 0.3 | Peers scoring below this are ranked last in peer selection, regardless of latency. |

### Initial score

A newly admitted peer starts with a score of `0.5` (neutral). Its score adjusts rapidly — the exponential moving average on latency and the 20-response sliding window on failure rate mean that a peer's true quality is reflected within its first ~10 interactions.

Exception: peers admitted with low discovery trust (ts-spec-007, section 6) start at `0.3` instead of `0.5`, reflecting the higher initial uncertainty.

### Score updates are synchronous

Scoring is updated inline when a response is processed — not in a background task. This is deliberate: scoring is a lightweight dict update (no I/O, no allocation), and synchronous updates ensure the Request Scheduler always sees the freshest scores when making its next selection decision.

## 5. Request Pipeline

The request pipeline controls how many requests are in-flight simultaneously and how they flow from selection to completion. It is the bridge between the selection algorithms (sections 2–3) and the wire protocol (ts-spec-005).

### Concurrency limits

| Limit | Scope | Default | Purpose |
|-------|-------|---------|---------|
| `max_requests_per_peer` | Per peer per swarm | 5 | Prevents overwhelming a single peer. Bounds the damage if a peer is slow or malicious. |
| `max_requests_per_swarm` | Per swarm | 20 | Bounds total concurrency per mosaic. Controls memory usage (each in-flight request holds a pending coroutine and timeout timer). |

Both limits are enforced by an `asyncio.Semaphore` per scope. The per-swarm semaphore is the outer bound; the per-peer limit is checked inside it. A request that cannot acquire both semaphores is not issued — the tessera remains in the selection queue.

### Request lifecycle

```
     select()          send REQUEST         receive PIECE/REJECT/timeout
        │                   │                         │
   ┌────▼────┐        ┌────▼────┐               ┌────▼────┐
   │ QUEUED  │───────►│IN_FLIGHT│──────────────►│RESOLVED │
   └─────────┘        └────┬────┘               └────┬────┘
                           │                         │
                      timeout/cancel            ┌────▼────┐
                           │                    │ VERIFY  │
                      ┌────▼────┐               └────┬────┘
                      │ FAILED  │                    │
                      └────┬────┘            pass    │   fail
                           │              ┌──────────┴──────────┐
                      re-queue            │                     │
                           │         ┌────▼────┐          ┌────▼────┐
                           └────────►│COMPLETE │          │RE-QUEUE │
                                     └─────────┘          └─────────┘
```

| State | Description |
|-------|-------------|
| **QUEUED** | Tessera selected by piece selection, awaiting a semaphore slot and peer assignment. |
| **IN_FLIGHT** | REQUEST sent. A timeout timer is running. Waiting for PIECE, REJECT, or timeout. |
| **RESOLVED** | Response received. If PIECE, proceed to VERIFY. If REJECT or timeout, proceed to FAILED. |
| **VERIFY** | Piece Verifier hashes the data and checks against the manifest (ts-spec-006, section 7). |
| **COMPLETE** | Tessera verified, written to disk, HAVE broadcast. Semaphore released. |
| **FAILED** | Request did not succeed. Peer scored accordingly. Tessera re-enters QUEUED for a different peer. |
| **RE-QUEUE** | Hash verification failed. Peer scored down. Tessera re-enters QUEUED. |

### Timeout handling

Each in-flight request has an independent timeout timer (default `request_timeout = 30s`, configurable via ts-spec-010).

When a timeout fires:

1. The request transitions to FAILED.
2. The Peer Scorer records the timeout as a failure for the serving peer.
3. The tessera re-enters QUEUED with the timed-out peer excluded from peer selection for this specific index (cooldown period: `peer_cooldown = 60s`).
4. If the peer accumulates `max_consecutive_timeouts` (default 3) across any requests, it is treated as unavailable (ts-spec-007, section 8).

### Retry policy

Failed requests (timeout, REJECT with `NOT_AVAILABLE` or `OVERLOADED`) are retried automatically:

| Failure type | Retry behavior |
|-------------|----------------|
| Timeout | Immediate re-queue. Timed-out peer excluded for `peer_cooldown`. |
| `NOT_AVAILABLE` | Immediate re-queue. Peer's bitfield updated (bit cleared for this index). |
| `OVERLOADED` | Re-queue after backoff: `min(2^attempt × 1s, 30s)`. Same peer eligible after backoff. |
| `HASH_MISMATCH` | Immediate re-queue. Poisoning peer scored down and excluded permanently for this index. |
| `INDEX_OUT_OF_RANGE` | Not retried. Logged as a scheduler bug. |

A tessera is retried up to `max_retries` times (default 10) across all peers. After exhausting retries, the tessera is marked as **stuck** and reported to the Application Interface. The transfer continues for other tesserae — a single stuck tessera does not block the entire mosaic.

### Pipeline scheduling loop

The Request Scheduler runs a continuous loop within each swarm's asyncio task:

```python
async def scheduling_loop(self):
    while not self.mosaic_complete:
        # 1. Fill available slots
        while self.can_issue_request():
            index = self.select_next_tessera()
            if index is None:
                break  # nothing to request or all peers at capacity
            peer = self.select_peer(index)
            if peer is None:
                self.backlog.add(index)
                break
            await self.issue_request(peer, index)

        # 2. Wait for any in-flight request to resolve
        await self.wait_for_completion()

        # 3. Process backlog if capacity freed
        self.drain_backlog()
```

The loop is event-driven — `wait_for_completion()` yields until a PIECE, REJECT, or timeout fires, at which point the scheduler re-evaluates available slots and pending work.

## 6. Endgame Mode

The final tesserae of a mosaic are the most vulnerable to slow completion. If the last few pieces are only available from slow or unresponsive peers, the entire transfer stalls while waiting. Endgame mode addresses this by requesting remaining tesserae from multiple peers simultaneously.

### Entry criteria

The Request Scheduler transitions from normal mode to endgame mode when **both** conditions are met:

1. The number of remaining (un-verified) tesserae is ≤ `endgame_threshold` (default: `max_requests_per_swarm`, i.e., 20).
2. All remaining tesserae have been requested at least once (no un-requested pieces remain).

Condition 2 prevents premature endgame activation — if there are 15 tesserae remaining but only 5 have been requested, the scheduler should fill the remaining slots normally before entering endgame.

### Behavior

In endgame mode, the normal "no duplicate requests" rule is suspended:

1. For each remaining tessera, the scheduler sends REQUEST to **every** connected peer that holds it (per their bitfield), regardless of whether another peer already has an in-flight request for the same index.
2. Per-peer concurrency limits (`max_requests_per_peer`) are still enforced. If a peer is at capacity, the duplicate request is not sent to that peer.
3. The per-swarm concurrency limit (`max_requests_per_swarm`) is **raised** to `remaining_count × connected_peers` during endgame, capped at `max_endgame_requests` (default: 100). This temporary increase accommodates the burst of duplicate requests.

### Cancellation

When a tessera is received and verified from one peer during endgame:

1. The scheduler sends CANCEL(index) to all other peers that have an in-flight request for the same index (ts-spec-005, section 5.3).
2. If a PIECE for the same index arrives after verification (from a peer that sent it before receiving the CANCEL), it is silently discarded — the tessera is already written to disk.
3. A peer receiving CANCEL after already sending the PIECE treats it as a no-op.

### Cancellation is best-effort

CANCEL messages may arrive after the peer has already committed resources to reading and sending the tessera. The goal is bandwidth savings, not guaranteed suppression. In a swarm of tens of peers with 20 remaining tesserae, the duplicate traffic during endgame is bounded and brief.

### Exit criteria

Endgame mode ends when:

- All tesserae are verified → mosaic complete, or
- The number of remaining tesserae increases (a previously verified tessera failed whole-file verification) → revert to normal mode.

### Why not always use endgame?

Endgame mode trades bandwidth for latency. Sending duplicate requests wastes upload capacity on peers that serve tesserae only to have them discarded. In normal mode with many remaining pieces, this waste is significant. Endgame is only efficient when the remaining piece count is small enough that the duplicated traffic is acceptable relative to the time savings.

## 7. Transfer Metrics & Progress

The Request Scheduler and Peer Scorer collect data that is useful beyond internal decision-making. This section specifies the metrics exposed to the Application Interface for progress reporting, monitoring, and agent consumption.

### Progress tracking

| Metric | Type | Computation |
|--------|------|-------------|
| `tesserae_total` | Integer | `manifest.tessera_count` |
| `tesserae_verified` | Integer | Count of tesserae that have passed hash verification and been written to disk. |
| `tesserae_in_flight` | Integer | Count of tesserae with an active in-flight REQUEST. |
| `tesserae_remaining` | Integer | `tesserae_total - tesserae_verified` |
| `progress_ratio` | Float (0.0–1.0) | `tesserae_verified / tesserae_total`. Returns 1.0 for empty mosaics (0 tesserae). |
| `bytes_received` | Integer | Total verified tessera bytes written to disk. |
| `bytes_total` | Integer | `manifest.file_size` |

### Throughput measurement

Throughput is measured as a sliding-window average over the last `throughput_window` seconds (default: 10):

```
throughput_bps = bytes_received_in_window / window_duration
```

The window tracks timestamped completion events. Each time a tessera is verified, a `(timestamp, tessera_size)` entry is appended. Entries older than `throughput_window` are pruned. This produces a responsive throughput estimate that reflects recent performance, not lifetime average.

### Estimated time remaining

```
eta_seconds = bytes_remaining / throughput_bps
```

Where `bytes_remaining = bytes_total - bytes_received`. If `throughput_bps` is zero (no tesserae received yet, or throughput window is empty), the ETA is reported as `None` — the Application Interface displays "unknown" rather than infinity.

ETA is inherently noisy. It is computed on demand (when `status()` is called), not continuously. No smoothing is applied — the caller may apply its own averaging if desired.

### Per-peer metrics

The following are exposed per connected peer, sourced from the Peer Scorer:

| Metric | Type | Description |
|--------|------|-------------|
| `agent_id` | bytes | Peer identity. |
| `score` | Float (0.0–1.0) | Current composite score. |
| `latency_ms` | Float | Exponential moving average latency. |
| `failure_rate` | Float (0.0–1.0) | Failure ratio over sliding window. |
| `bytes_delivered` | Integer | Cumulative verified bytes from this peer. |
| `hash_mismatches` | Integer | Lifetime count of poisoned tesserae from this peer. |
| `in_flight` | Integer | Number of currently in-flight requests to this peer. |

### Swarm-level metrics

| Metric | Type | Description |
|--------|------|-------------|
| `connected_peers` | Integer | Number of peers with active channels. |
| `seeders` | Integer | Peers with complete bitfields. |
| `leechers` | Integer | Peers with incomplete bitfields. |
| `swarm_state` | Enum | PENDING, ACTIVE, DRAINING, or CLOSED (ts-spec-007, section 2). |
| `mode` | Enum | NORMAL or ENDGAME. |
| `stuck_tesserae` | List[int] | Indices of tesserae that exhausted `max_retries`. Empty in healthy transfers. |

### Status snapshot

All metrics above are bundled into a `TransferStatus` dataclass returned by `status(manifest_hash)` (ts-spec-010):

```python
@dataclass
class TransferStatus:
    manifest_hash: bytes
    state: SwarmState
    mode: TransferMode
    progress: float
    bytes_received: int
    bytes_total: int
    throughput_bps: float
    eta_seconds: float | None
    tesserae_verified: int
    tesserae_total: int
    tesserae_in_flight: int
    stuck_tesserae: list[int]
    peers: list[PeerStatus]
```

This snapshot is computed on demand — it is not continuously maintained. The Application Interface and CLI read it when the user or agent calls `status()`. Agent callers (G6 in ts-spec-001) can use `TransferStatus` programmatically to make decisions about whether to wait, cancel, or adjust.

---

## 8. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| R1 | ts-spec-001 — Vision & Scope | Goal G4 (decentralized transfer from multiple peers), G5 (AI-augmented operations), G6 (agent-native API for programmatic status consumption) |
| R2 | ts-spec-002 — Glossary | Defines tessera, mosaic, bitfield, seeder, leecher, Request Scheduler, Peer Scorer, Bitfield Manager |
| R3 | ts-spec-003 — Threat Model | T1 (piece poisoning) mitigated by hash mismatch scoring, T5 (selective withholding) mitigated by peer scoring and timeout detection |
| R4 | ts-spec-004 — System Architecture | Request Scheduler, Peer Scorer, Bitfield Manager component definitions (section 3.1); SelectionStrategy and ScoringFunction extension points (section 8); per-swarm concurrency model (section 7) |
| R5 | ts-spec-005 — Wire Protocol Addendum | REQUEST, PIECE, CANCEL, REJECT message formats (section 4); endgame flow diagram (section 5.3) |
| R6 | ts-spec-006 — Content Addressing Spec | Per-tessera hash verification (section 7) that drives HASH_MISMATCH scoring |
| R7 | ts-spec-007 — Swarm & Peer Discovery | Peer eviction triggers (section 3) driven by Peer Scorer thresholds; capacity rebalancing (section 7); network partition detection via consecutive timeouts (section 8); discovery trust levels affecting initial score (section 6) |
| R8 | ts-spec-009 — AI Integration Spec | Intelligence Bridge hints for piece selection and peer ranking |
| R9 | ts-spec-010 — API & CLI Design | TesseraConfig defaults for concurrency limits, timeouts, thresholds; status() API returning TransferStatus |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
