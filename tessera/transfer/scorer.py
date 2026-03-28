"""Peer Scorer — real-time quality scoring for connected peers.

Spec: ts-spec-008 §4

Each peer has four tracked metrics:
  latency_ms       — EMA with α = 0.3
  failure_rate     — sliding window of last scoring_window responses
  bytes_delivered  — cumulative verified bytes (not decayed)
  hash_mismatches  — lifetime count of poisoned tesserae (not windowed)

These combine via a weighted formula into a single 0.0–1.0 score.
The ScoringFunction extension point allows the default formula to be
replaced by a custom callable (e.g. AI-driven scoring via ts-spec-009).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EMA_ALPHA: float = 0.3
_MAX_ACCEPTABLE_LATENCY_MS: float = 5_000.0
_THROUGHPUT_BASELINE_BYTES: float = 10 * 1024 * 1024  # 10 MB
_DEFAULT_SCORING_WINDOW: int = 20
_DEFAULT_INITIAL_SCORE: float = 0.5
_LOW_TRUST_INITIAL_SCORE: float = 0.3

# Score thresholds (ts-spec-010 §4 defaults)
MIN_PEER_SCORE: float = 0.1
EVICTION_THRESHOLD: float = 0.2
DEPRIORITIZE_THRESHOLD: float = 0.3
PENALTY_PER_MISMATCH: float = 0.25


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PeerMetrics:
    """Raw metrics for one peer — input to the scoring function."""

    latency_ms: float = 0.0
    failure_rate: float = 0.0
    bytes_delivered: int = 0
    hash_mismatches: int = 0


# Callable type for custom scoring (ts-spec-008 §4, ScoringFunction extension)
ScoringFunction = Callable[[PeerMetrics], float]


# ---------------------------------------------------------------------------
# Default scoring function
# ---------------------------------------------------------------------------


def default_scoring_function(
    m: PeerMetrics,
    *,
    w_latency: float = 0.3,
    w_failure: float = 0.4,
    w_throughput: float = 0.3,
    penalty: float = PENALTY_PER_MISMATCH,
    max_latency_ms: float = _MAX_ACCEPTABLE_LATENCY_MS,
    throughput_baseline: float = _THROUGHPUT_BASELINE_BYTES,
) -> float:
    """Compute a 0.0–1.0 composite score from *m*."""
    latency_score = 1.0 - min(m.latency_ms / max_latency_ms, 1.0)
    failure_score = 1.0 - m.failure_rate
    throughput_score = min(m.bytes_delivered / throughput_baseline, 1.0)

    raw = (
        w_latency * latency_score
        + w_failure * failure_score
        + w_throughput * throughput_score
        - penalty * m.hash_mismatches
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Per-peer internal state
# ---------------------------------------------------------------------------


@dataclass
class _PeerState:
    score: float
    metrics: PeerMetrics = field(default_factory=PeerMetrics)
    _window: deque[bool] = field(
        default_factory=lambda: deque(maxlen=_DEFAULT_SCORING_WINDOW)
    )

    def update_failure_rate(self) -> None:
        if self._window:
            self.metrics.failure_rate = sum(1 for v in self._window if not v) / len(
                self._window
            )


# ---------------------------------------------------------------------------
# PeerScorer
# ---------------------------------------------------------------------------


class PeerScorer:
    """Maintain per-peer metrics and compute composite scores.

    Args:
        scoring_fn: Scoring function. Defaults to default_scoring_function.
        scoring_window: Sliding window size for failure rate.
        w_latency: Weight for latency component.
        w_failure: Weight for failure-rate component.
        w_throughput: Weight for throughput component.
        penalty_mismatch: Per-mismatch score penalty.
        min_peer_score: Eviction hard floor.
        eviction_threshold: Soft eviction threshold for rebalancing.
        deprioritize_threshold: Below this score the peer is ranked last.
    """

    def __init__(
        self,
        scoring_fn: ScoringFunction | None = None,
        scoring_window: int = _DEFAULT_SCORING_WINDOW,
        w_latency: float = 0.3,
        w_failure: float = 0.4,
        w_throughput: float = 0.3,
        penalty_mismatch: float = PENALTY_PER_MISMATCH,
        min_peer_score: float = MIN_PEER_SCORE,
        eviction_threshold: float = EVICTION_THRESHOLD,
        deprioritize_threshold: float = DEPRIORITIZE_THRESHOLD,
    ) -> None:
        self._scoring_fn = scoring_fn
        self._scoring_window = scoring_window
        self._w_latency = w_latency
        self._w_failure = w_failure
        self._w_throughput = w_throughput
        self._penalty = penalty_mismatch
        self._min_score = min_peer_score
        self._eviction_threshold = eviction_threshold
        self._deprioritize_threshold = deprioritize_threshold
        self._peers: dict[bytes, _PeerState] = {}

    # ------------------------------------------------------------------
    # Peer lifecycle
    # ------------------------------------------------------------------

    def add_peer(self, peer_id: bytes, *, low_trust: bool = False) -> None:
        """Register a new peer with an initial score of 0.5 (or 0.3 for low trust)."""
        initial = _LOW_TRUST_INITIAL_SCORE if low_trust else _DEFAULT_INITIAL_SCORE
        self._peers[peer_id] = _PeerState(
            score=initial,
            _window=deque(maxlen=self._scoring_window),
        )

    def remove_peer(self, peer_id: bytes) -> None:
        """Deregister a peer."""
        self._peers.pop(peer_id, None)

    def has_peer(self, peer_id: bytes) -> bool:
        return peer_id in self._peers

    # ------------------------------------------------------------------
    # Metric updates
    # ------------------------------------------------------------------

    def on_piece_received(
        self, peer_id: bytes, latency_ms: float, tessera_size: int
    ) -> None:
        """Update metrics after a successful piece delivery."""
        state = self._peers[peer_id]
        # EMA update for latency.
        state.metrics.latency_ms = (
            _EMA_ALPHA * latency_ms + (1.0 - _EMA_ALPHA) * state.metrics.latency_ms
        )
        # Sliding window: record success.
        state._window.append(True)
        state.update_failure_rate()
        state.metrics.bytes_delivered += tessera_size
        state.score = self._compute(state.metrics)

    def on_failure(self, peer_id: bytes) -> None:
        """Record a request failure (timeout, NOT_AVAILABLE, OVERLOADED)."""
        state = self._peers[peer_id]
        state._window.append(False)
        state.update_failure_rate()
        state.score = self._compute(state.metrics)

    def on_hash_mismatch(self, peer_id: bytes) -> None:
        """Record a poisoned tessera (HASH_MISMATCH). Permanent, not windowed."""
        state = self._peers[peer_id]
        state.metrics.hash_mismatches += 1
        state._window.append(False)
        state.update_failure_rate()
        state.score = self._compute(state.metrics)

    # ------------------------------------------------------------------
    # Score queries
    # ------------------------------------------------------------------

    def score(self, peer_id: bytes) -> float:
        """Return the current composite score for *peer_id*."""
        return self._peers[peer_id].score

    def metrics(self, peer_id: bytes) -> PeerMetrics:
        """Return a copy of the raw metrics for *peer_id*."""
        m = self._peers[peer_id].metrics
        return PeerMetrics(
            latency_ms=m.latency_ms,
            failure_rate=m.failure_rate,
            bytes_delivered=m.bytes_delivered,
            hash_mismatches=m.hash_mismatches,
        )

    def should_evict(self, peer_id: bytes) -> bool:
        """Return True if the peer's score is below the hard eviction floor."""
        return self._peers[peer_id].score < self._min_score

    def should_displace(self, peer_id: bytes) -> bool:
        """Return True if the peer may be displaced during rebalancing."""
        return self._peers[peer_id].score < self._eviction_threshold

    def is_deprioritized(self, peer_id: bytes) -> bool:
        """Return True if the peer should be ranked last in selection."""
        return self._peers[peer_id].score < self._deprioritize_threshold

    def all_scores(self) -> dict[bytes, float]:
        """Return {peer_id: score} for all registered peers."""
        return {pid: s.score for pid, s in self._peers.items()}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute(self, m: PeerMetrics) -> float:
        if self._scoring_fn is not None:
            return self._scoring_fn(m)
        return default_scoring_function(
            m,
            w_latency=self._w_latency,
            w_failure=self._w_failure,
            w_throughput=self._w_throughput,
            penalty=self._penalty,
        )
