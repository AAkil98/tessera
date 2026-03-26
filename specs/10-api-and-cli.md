# API & CLI Design

```yaml
id: ts-spec-010
type: spec
status: stable
created: 2026-03-17
revised: 2026-03-26
authors:
  - Akil Abderrahim
  - Claude Opus 4.6
tags: [api, cli, configuration, tessera]
```

## Table of Contents

1. Purpose & Scope
2. Public API
3. CLI Commands
4. TesseraConfig
5. Error Handling
6. Event Callbacks
7. References

---

## 1. Purpose & Scope

This document defines Tessera's public surface — the API that Python callers use to publish, fetch, and manage mosaics, the CLI that wraps it for terminal use, and the configuration object that ties together every configurable value referenced across specs 04–09.

### What this spec defines

- **Public API.** The five Python functions — `publish()`, `fetch()`, `query()`, `status()`, `cancel()` — their signatures, parameters, return types, and async semantics. This is the library entry point described in ts-spec-004, section 3.3.
- **CLI commands.** The command-line interface that maps terminal commands to API calls. Designed for human operators and shell scripts.
- **TesseraConfig.** The single configuration dataclass that every other component reads. Centralizes all configurable defaults that prior specs referenced as "configurable via ts-spec-010."
- **Error handling.** The exception hierarchy and error semantics. How API callers distinguish between recoverable and fatal errors.
- **Event callbacks.** The `on_manifest_created`, `on_manifest_received`, and progress callback hooks from ts-spec-004 (section 8, Manifest Hooks).

### What this spec does not define

| Concern | Owner |
|---------|-------|
| Internal component interfaces (Chunker, Assembler, etc.) | ts-spec-004 |
| Wire message format | ts-spec-005 |
| Manifest binary format | ts-spec-006 |
| Discovery backend implementations | ts-spec-007 |
| Piece selection and peer scoring internals | ts-spec-008 |
| AI adapter prompts and sanitization logic | ts-spec-009 |
| On-disk storage layout | ts-spec-011 |

### Design principles

- **Library first** (G7 in ts-spec-001). The API is the primary interface. The CLI is a thin wrapper around it. No functionality exists only in the CLI.
- **Agent-native** (G6). Every API function is `async`, returns structured data (dataclasses, not formatted strings), and is designed to be called by autonomous agents as naturally as by humans.
- **20-line cycle** (SC5). A complete publish-discover-fetch cycle should be expressible in under 20 lines of application code.
- **Fail explicit.** Errors are typed exceptions, not return codes or sentinel values. The caller always knows what went wrong and whether it can retry.

## 2. Public API

The public API consists of five async functions and one constructor. All are importable from `tessera`:

```python
from tessera import TesseraNode, TesseraConfig
```

### TesseraNode

The entry point. A `TesseraNode` encapsulates a running Tessera instance — one MFP agent, one Swarm Manager, one Transfer Engine.

```python
class TesseraNode:
    def __init__(self, config: TesseraConfig | None = None):
        """
        Create a Tessera node.

        Args:
            config: Configuration. If None, all defaults are used.
        """

    async def start(self) -> None:
        """
        Bind the MFP agent and start background tasks.
        Must be called before any other method.
        """

    async def stop(self) -> None:
        """
        Graceful shutdown. Transitions all swarms to DRAINING,
        waits for in-flight operations, unbinds the MFP agent.
        """

    async def __aenter__(self) -> "TesseraNode": ...
    async def __aexit__(self, *exc) -> None: ...
```

`TesseraNode` supports `async with` for automatic start/stop:

```python
async with TesseraNode(config) as node:
    manifest_hash = await node.publish("report.pdf")
```

### publish()

```python
async def publish(
    self,
    file_path: str | Path,
    metadata: dict[str, str] | None = None,
    skip_moderation: bool = False,
) -> bytes:
    """
    Chunk a file, build the manifest, announce to discovery, and begin seeding.

    Args:
        file_path: Path to the file to publish.
        metadata: Optional metadata key-value pairs. 'name' is auto-populated
                  from the filename if not provided.
        skip_moderation: If True, bypass the content moderation gate.

    Returns:
        The manifest hash (32 bytes). This is the mosaic's identity.

    Raises:
        FileNotFoundError: file_path does not exist.
        ModerationError: Content moderation rejected the file (and skip_moderation is False).
        CapacityError: max_swarms_per_node reached.
        TesseraError: Chunking or manifest creation failed.
    """
```

### fetch()

```python
async def fetch(
    self,
    manifest_hash: bytes,
    output_path: str | Path | None = None,
    skip_moderation: bool = False,
    on_progress: Callable[[TransferStatus], None] | None = None,
) -> Path:
    """
    Join the swarm for a mosaic, download all tesserae, and assemble the file.

    Args:
        manifest_hash: The 32-byte manifest hash identifying the mosaic.
        output_path: Where to write the assembled file. If None, uses the
                     filename from the manifest metadata in the current directory.
        skip_moderation: If True, bypass the content moderation gate.
        on_progress: Optional callback invoked after each tessera is verified.
                     Receives a TransferStatus snapshot.

    Returns:
        Path to the assembled file on disk.

    Raises:
        ModerationError: Content moderation rejected the manifest metadata.
        CapacityError: max_swarms_per_node reached.
        StarvationError: No peers found within starvation_timeout.
        IntegrityError: Whole-file verification failed after max retries.
        TesseraError: Transfer failed for another reason.
    """
```

### query()

```python
async def query(
    self,
    text: str,
    max_results: int = 10,
) -> list[DiscoveryResult]:
    """
    Search for mosaics by natural-language description.
    Requires madakit (ts-spec-009). Returns an empty list if madakit
    is not configured or the LLM call fails.

    Args:
        text: Natural-language query.
        max_results: Maximum number of results to return.

    Returns:
        List of DiscoveryResult, sorted by relevance_score descending.
        Empty list if no matches or madakit is unavailable.
    """
```

### status()

```python
async def status(
    self,
    manifest_hash: bytes | None = None,
) -> TransferStatus | list[TransferStatus] | NodeStatus:
    """
    Get transfer and node status.

    Args:
        manifest_hash: If provided, return status for that specific mosaic.
                       If None, return status for all active swarms.

    Returns:
        TransferStatus for a specific mosaic (ts-spec-008, section 7),
        list of TransferStatus for all active swarms, or NodeStatus
        if no swarms are active.

    Raises:
        KeyError: manifest_hash is not an active swarm.
    """
```

```python
@dataclass
class NodeStatus:
    agent_id: bytes
    active_swarms: int
    total_peers: int
    capacity_remaining: int      # max_swarms_per_node - active_swarms
    ai: AIStatus | None          # None if madakit not configured
```

### cancel()

```python
async def cancel(
    self,
    manifest_hash: bytes,
) -> None:
    """
    Cancel an active transfer and leave the swarm.

    Transitions the swarm to DRAINING. In-flight pieces are allowed to
    complete. The swarm is fully closed when draining finishes.

    Args:
        manifest_hash: The mosaic to cancel.

    Raises:
        KeyError: manifest_hash is not an active swarm.
    """
```

### SC5 demonstration

A complete publish-discover-fetch cycle in under 20 lines:

```python
import asyncio
from tessera import TesseraNode, TesseraConfig

async def main():
    config = TesseraConfig()

    async with TesseraNode(config) as publisher:
        manifest_hash = await publisher.publish("report.pdf",
            metadata={"description": "Q3 revenue report"})
        print(f"Published: {manifest_hash.hex()}")

    async with TesseraNode(config) as fetcher:
        results = await fetcher.query("Q3 revenue")
        if results:
            path = await fetcher.fetch(results[0].manifest_hash)
            print(f"Fetched: {path}")

asyncio.run(main())
```

14 lines of application code.

---

## 3. CLI Commands

The CLI is a thin wrapper around the public API. Every command maps to exactly one `TesseraNode` method. No functionality exists only in the CLI (G7).

### Invocation

```
tessera <command> [options]
```

Global options apply to all commands:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--config` | path | None | Path to a TOML config file. Overrides all defaults. |
| `--data-dir` | path | `~/.tessera` | Root storage directory (ts-spec-011). |
| `--bind` | host:port | `0.0.0.0:0` | MFP agent bind address. |
| `--tracker` | URL | None | Tracker URL. May be specified multiple times. |
| `--log-level` | str | `info` | Logging verbosity: `debug`, `info`, `warning`, `error`. |
| `--json` | flag | False | Emit machine-readable JSON instead of human-friendly text. |

### tessera publish

```
tessera publish <file> [--meta KEY=VALUE ...] [--skip-moderation]
```

Maps to `TesseraNode.publish()`.

| Argument / Option | Maps to | Notes |
|-------------------|---------|-------|
| `<file>` | `file_path` | Required positional argument. |
| `--meta KEY=VALUE` | `metadata` | Repeatable. Parsed into `dict[str, str]`. |
| `--skip-moderation` | `skip_moderation` | Flag. |

**Output (text):**
```
Published: a3f2...c891
Seeding. Press Ctrl-C to stop.
```

**Output (--json):**
```json
{"manifest_hash": "a3f2...c891", "status": "seeding"}
```

The process remains alive and seeds until interrupted. On `SIGINT` / `SIGTERM`, the node drains gracefully before exiting.

### tessera fetch

```
tessera fetch <manifest_hash> [--output PATH] [--skip-moderation]
```

Maps to `TesseraNode.fetch()`.

| Argument / Option | Maps to | Notes |
|-------------------|---------|-------|
| `<manifest_hash>` | `manifest_hash` | Hex-encoded 32-byte hash. |
| `--output` | `output_path` | Optional. Defaults to filename from manifest metadata. |
| `--skip-moderation` | `skip_moderation` | Flag. |

A progress bar is displayed during download (unless `--json`). The `on_progress` callback is wired to the progress bar internally.

**Output (text):**
```
Fetching: report.pdf
[████████████████████░░░░░] 84%  12.3 MB/s  ETA 3s
Complete: ./report.pdf (52.1 MB, SHA-256 verified)
```

**Output (--json):** Streams newline-delimited JSON with periodic `TransferStatus` snapshots:
```json
{"event": "progress", "pieces_done": 168, "pieces_total": 200, "throughput_bps": 12900000}
{"event": "complete", "path": "./report.pdf", "size": 54634496}
```

### tessera query

```
tessera query <text> [--max-results N]
```

Maps to `TesseraNode.query()`. Requires madakit.

| Argument / Option | Maps to | Notes |
|-------------------|---------|-------|
| `<text>` | `text` | Natural-language search string. |
| `--max-results` | `max_results` | Default: 10. |

**Output (text):**
```
  #  Score  Hash                                                              Name
  1  0.92   a3f2...c891  Q3 revenue report
  2  0.71   b8e1...4d20  Q3 expense summary
```

**Output (--json):**
```json
[{"manifest_hash": "a3f2...c891", "name": "Q3 revenue report", "relevance_score": 0.92}, ...]
```

Exits with code 0 even if no results are found (empty list is not an error). Exits with code 1 if madakit is not configured.

### tessera status

```
tessera status [<manifest_hash>]
```

Maps to `TesseraNode.status()`.

| Argument / Option | Maps to | Notes |
|-------------------|---------|-------|
| `<manifest_hash>` | `manifest_hash` | Optional. If omitted, shows all active swarms. |

**Output (text, specific mosaic):**
```
Mosaic:     a3f2...c891
State:      ACTIVE
Progress:   168 / 200 (84.0%)
Peers:      7
Throughput: 12.3 MB/s
ETA:        3s
```

**Output (text, all swarms):**
```
Active swarms: 3 / 10

  Hash              State     Progress    Peers  Throughput
  a3f2...c891       ACTIVE    84.0%       7      12.3 MB/s
  b8e1...4d20       ACTIVE    12.5%       3       4.1 MB/s
  c7d3...9a12       DRAINING  100.0%      2       0.0 MB/s
```

### tessera cancel

```
tessera cancel <manifest_hash>
```

Maps to `TesseraNode.cancel()`.

| Argument / Option | Maps to | Notes |
|-------------------|---------|-------|
| `<manifest_hash>` | `manifest_hash` | Required. Hex-encoded. |

**Output (text):**
```
Cancelling a3f2...c891 — draining in-flight pieces...
Cancelled.
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | Application error (moderation rejected, madakit unavailable, etc.). |
| 2 | Usage error (bad arguments, missing required options). |
| 3 | File I/O error (file not found, permission denied, disk full). |
| 4 | Network error (starvation timeout, no peers). |
| 5 | Integrity error (whole-file verification failed). |

---

## 4. TesseraConfig

The single configuration object read by every component. All values referenced as "configurable via ts-spec-010" in prior specs are defined here.

```python
@dataclass
class TesseraConfig:
    """
    Complete Tessera configuration.

    All fields have sensible defaults. Pass to TesseraNode() to override.
    """

    # --- Node identity ---
    data_dir: Path = Path("~/.tessera")
    """Root directory for all on-disk state (ts-spec-011)."""

    bind_address: str = "0.0.0.0"
    """MFP agent bind host."""

    bind_port: int = 0
    """MFP agent bind port. 0 = OS-assigned."""

    # --- Chunking (ts-spec-006) ---
    tessera_size: int = 262_144
    """Default tessera size in bytes (256 KB). Must be ≤ max_payload_size - 5."""

    # --- Swarm management (ts-spec-007) ---
    max_peers_per_swarm: int = 50
    """Maximum concurrent peers in a single swarm."""

    max_swarms_per_node: int = 10
    """Maximum concurrent swarms this node participates in."""

    eviction_threshold: float = 0.2
    """Peer score below which a peer is evicted (ts-spec-008)."""

    starvation_timeout: float = 120.0
    """Seconds with zero peers before a fetch raises StarvationError."""

    starvation_backoff_base: float = 5.0
    """Base delay (seconds) for exponential backoff during starvation re-discovery."""

    starvation_backoff_max: float = 60.0
    """Maximum backoff delay (seconds) between re-discovery attempts."""

    # --- Transfer engine (ts-spec-008) ---
    max_requests_per_peer: int = 5
    """Maximum concurrent piece requests to a single peer."""

    max_requests_per_swarm: int = 20
    """Maximum concurrent piece requests across all peers in a swarm."""

    request_timeout: float = 30.0
    """Seconds before a piece request times out."""

    max_retries_per_tessera: int = 10
    """Maximum retry attempts for a single tessera before marking it stuck."""

    endgame_threshold: int = 20
    """Enter endgame mode when remaining pieces ≤ this value and all are requested."""

    max_endgame_requests: int = 100
    """Maximum total duplicate requests during endgame mode."""

    # --- Peer scoring (ts-spec-008) ---
    score_weight_latency: float = 0.3
    """Weight for latency metric in peer scoring."""

    score_weight_failure: float = 0.4
    """Weight for failure-rate metric in peer scoring."""

    score_weight_throughput: float = 0.3
    """Weight for throughput metric in peer scoring."""

    score_penalty_mismatch: float = 0.25
    """Penalty per hash mismatch in peer scoring."""

    score_min: float = 0.1
    """Minimum score; peers below this are evicted."""

    score_deprioritize: float = 0.3
    """Score below which peers are deprioritized in selection."""

    # --- Discovery (ts-spec-007) ---
    discovery_backends: list[str] = field(default_factory=lambda: ["tracker"])
    """Active discovery backend names. Each must have a corresponding backend registered."""

    tracker_urls: list[str] = field(default_factory=list)
    """Tracker endpoint URLs for the default TrackerBackend."""

    tracker_announce_interval: float = 1800.0
    """Seconds between tracker re-announce (30 minutes)."""

    # --- AI integration (ts-spec-009) ---
    ai_enabled: bool = True
    """Enable madakit integration. If True but madakit is not installed, degrades silently."""

    ai_moderation_on_publish: bool = True
    """Run content moderation before publishing."""

    ai_moderation_on_fetch: bool = True
    """Run content moderation before fetching."""

    ai_ranking_interval: float = 60.0
    """Seconds between AI-driven peer ranking updates."""

    ai_ranking_confidence_threshold: float = 0.7
    """Minimum confidence for AI ranking hints to influence peer selection."""

    # --- Timeouts and limits ---
    graceful_shutdown_timeout: float = 30.0
    """Seconds to wait for in-flight operations during shutdown."""

    max_metadata_keys: int = 64
    """Maximum number of key-value pairs in manifest metadata."""

    max_metadata_value_bytes: int = 1024
    """Maximum byte length of a single metadata value."""
```

### TOML file format

When loaded from a file (`--config`), the configuration uses TOML with section headers matching the field groupings:

```toml
data_dir = "~/.tessera"
bind_address = "0.0.0.0"
bind_port = 9100

[chunking]
tessera_size = 262144

[swarm]
max_peers_per_swarm = 50
max_swarms_per_node = 10
eviction_threshold = 0.2
starvation_timeout = 120.0

[transfer]
max_requests_per_peer = 5
max_requests_per_swarm = 20
request_timeout = 30.0

[scoring]
weight_latency = 0.3
weight_failure = 0.4
weight_throughput = 0.3

[discovery]
backends = ["tracker"]
tracker_urls = ["https://tracker.example.com/announce"]

[ai]
enabled = true
moderation_on_publish = true
moderation_on_fetch = true
```

### Configuration precedence

Values are resolved in order (later wins):

1. **Dataclass defaults** — the values shown above.
2. **TOML file** — loaded from the path given to `--config`.
3. **CLI flags** — `--data-dir`, `--bind`, `--tracker`, etc.
4. **Constructor arguments** — fields set directly on `TesseraConfig()` in code.

CLI flags and constructor arguments occupy the same precedence tier. In practice they do not conflict — CLI flags are only present when running from the terminal, and constructor arguments are only present when using the library API.

---

## 5. Error Handling

All Tessera exceptions inherit from a single base class. Callers can catch `TesseraError` to handle any Tessera failure, or catch specific subclasses for fine-grained control.

### Exception hierarchy

```
TesseraError
├── ModerationError
├── CapacityError
├── StarvationError
├── IntegrityError
├── ProtocolError
│   ├── HandshakeError
│   └── MessageError
└── ConfigError
```

### Exception definitions

```python
class TesseraError(Exception):
    """Base class for all Tessera exceptions."""

class ModerationError(TesseraError):
    """Content moderation rejected the operation.

    Attributes:
        reason: Human-readable explanation from the moderation adapter.
        manifest_hash: The manifest hash involved, if available.
    """
    reason: str
    manifest_hash: bytes | None

class CapacityError(TesseraError):
    """Node capacity exhausted.

    Raised when max_swarms_per_node is reached and a new publish() or
    fetch() is attempted.

    Attributes:
        current: Number of active swarms.
        maximum: The configured limit.
    """
    current: int
    maximum: int

class StarvationError(TesseraError):
    """No peers found within the starvation timeout.

    Raised by fetch() when the swarm has zero peers for longer than
    config.starvation_timeout seconds, after exhausting exponential
    backoff re-discovery attempts.

    Attributes:
        manifest_hash: The mosaic that could not be fetched.
        elapsed: Seconds spent waiting.
    """
    manifest_hash: bytes
    elapsed: float

class IntegrityError(TesseraError):
    """Whole-file verification failed.

    Raised by fetch() after the file is fully assembled but the
    SHA-256 of the reconstructed file does not match the manifest's
    file_hash. All per-tessera hashes passed — this indicates a
    Chunker/Assembler bug or a manifest that was built from a
    different file version.

    Attributes:
        manifest_hash: The mosaic's manifest hash.
        expected: The file hash declared in the manifest.
        actual: The hash of the assembled file.
    """
    manifest_hash: bytes
    expected: bytes
    actual: bytes

class ProtocolError(TesseraError):
    """Wire protocol violation.

    Base class for errors detected during peer communication.

    Attributes:
        peer_id: The AgentId of the peer that caused the error.
        error_code: The wire protocol error code (ts-spec-005).
    """
    peer_id: bytes
    error_code: int

class HandshakeError(ProtocolError):
    """Handshake failed or was rejected."""

class MessageError(ProtocolError):
    """Received a malformed or unexpected message."""

class ConfigError(TesseraError):
    """Invalid configuration.

    Raised during TesseraNode construction if TesseraConfig
    contains invalid or contradictory values.

    Attributes:
        field: The config field name.
        reason: Why the value is invalid.
    """
    field: str
    reason: str
```

### Recoverability

| Exception | Recoverable? | Recommended action |
|-----------|:---:|---|
| `ModerationError` | No | Inform user. Do not retry with the same content. |
| `CapacityError` | Yes | Wait for an active swarm to finish, or cancel one. |
| `StarvationError` | Maybe | Retry later — the mosaic may not have any online seeders. |
| `IntegrityError` | No | The manifest or file data is corrupt. Do not trust the output. |
| `ProtocolError` | Yes | The peer is misbehaving. The Swarm Manager evicts automatically; the transfer continues with other peers. |
| `ConfigError` | No | Fix the configuration and restart. |

### Error propagation

- **Within the library.** Internal components (Transfer Engine, Swarm Manager) raise domain-specific exceptions. The `TesseraNode` methods catch internal errors and re-raise them as the public exceptions listed above. Internal exception types are not exported.
- **In the CLI.** The CLI runner catches all `TesseraError` subclasses, prints a human-readable message (or JSON error object with `--json`), and exits with the appropriate exit code (section 3).
- **Cancellation.** `asyncio.CancelledError` is never wrapped. If the caller cancels a task, the cancellation propagates cleanly. In-flight piece requests are allowed to complete or time out during draining.

---

## 6. Event Callbacks

Tessera exposes three event hooks referenced in ts-spec-004 (section 8, Manifest Hooks). These allow callers to react to lifecycle events without polling.

### Registering callbacks

Callbacks are set on `TesseraNode` after construction:

```python
node = TesseraNode(config)
node.on_manifest_created = my_publish_handler
node.on_manifest_received = my_fetch_handler
node.on_transfer_complete = my_completion_handler
await node.start()
```

All callbacks are optional. If not set, the event is silently ignored.

### on_manifest_created

```python
on_manifest_created: Callable[[ManifestEvent], None] | None = None
```

Fired after `publish()` builds and signs the manifest, before announcing to discovery. The callback receives:

```python
@dataclass
class ManifestEvent:
    manifest_hash: bytes
    """The 32-byte manifest hash."""

    file_path: Path
    """Path to the source file."""

    file_size: int
    """Size of the source file in bytes."""

    tessera_count: int
    """Number of tesserae the file was chunked into."""

    metadata: dict[str, str]
    """The metadata that will be embedded in the manifest."""
```

Use case: logging, analytics, triggering external notifications when a file is published.

### on_manifest_received

```python
on_manifest_received: Callable[[ManifestEvent], None] | None = None
```

Fired after `fetch()` receives and validates a manifest from a peer, before piece transfer begins. The `ManifestEvent` is the same dataclass — `file_path` is the intended output path.

Use case: pre-allocation of disk space, UI updates showing file metadata, agent decision-making about whether to proceed with the download.

### on_transfer_complete

```python
on_transfer_complete: Callable[[TransferCompleteEvent], None] | None = None
```

Fired after a fetch completes successfully — all tesserae verified, file assembled, whole-file hash confirmed.

```python
@dataclass
class TransferCompleteEvent:
    manifest_hash: bytes
    """The mosaic's manifest hash."""

    output_path: Path
    """Path to the assembled file on disk."""

    file_size: int
    """Size of the assembled file in bytes."""

    elapsed: float
    """Total transfer time in seconds."""

    peers_used: int
    """Number of distinct peers that contributed pieces."""

    average_throughput: float
    """Average throughput in bytes per second over the transfer."""
```

Use case: post-download processing, chaining fetches in an agent workflow, audit logging.

### Callback semantics

- **Synchronous.** Callbacks are plain functions, not coroutines. They are invoked via `asyncio.get_event_loop().call_soon()` so they do not block the transfer. If a callback needs to perform async work, it should schedule a task internally.
- **Non-blocking contract.** Callbacks must return promptly. A callback that blocks will delay event processing for all swarms on the node.
- **Exception isolation.** If a callback raises, the exception is logged at `warning` level and swallowed. Callback failures never abort a transfer.
- **Threading.** Callbacks are always invoked on the asyncio event loop thread. No synchronization is needed for single-threaded callers.

### Progress callback (fetch-specific)

The `on_progress` parameter on `fetch()` (section 2) is not a node-level hook — it is per-transfer. It receives `TransferStatus` (ts-spec-008, section 7) after each verified tessera. The same semantics apply: synchronous, non-blocking, exception-isolated.

---

## 7. References

| Ref | Document | Relevance |
|-----|----------|-----------|
| ts-spec-001 | Vision & Scope | G6 (agent-native), G7 (library-first), SC5 (20-line cycle) |
| ts-spec-004 | System Architecture | Application Interface layer, manifest hooks (section 8), publish/fetch flows |
| ts-spec-005 | Wire Protocol Addendum | Error codes referenced by ProtocolError |
| ts-spec-006 | Content Addressing | Chunking defaults (tessera_size), manifest format, integrity verification |
| ts-spec-007 | Swarm & Peer Discovery | DiscoveryBackend, capacity limits, starvation timeout, tracker announce |
| ts-spec-008 | Piece Selection & Transfer | Peer scoring weights, request pipeline limits, endgame threshold, TransferStatus |
| ts-spec-009 | AI Integration | Moderation gates, ranking interval/confidence, graceful degradation |
| ts-spec-011 | Storage & State Management | data_dir layout (forward reference) |

---

*Tessera — authored by Akil Abderrahim and Claude Opus 4.6*
