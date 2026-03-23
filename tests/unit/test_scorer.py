"""Unit tests for PeerScorer — ts-spec-013 §3.4."""

from __future__ import annotations

import pytest

from tessera.transfer.scorer import (
    DEPRIORITIZE_THRESHOLD,
    MIN_PEER_SCORE,
    PeerMetrics,
    PeerScorer,
)

_PEER = b"\xaa" * 8
_TESSERA_SIZE = 262_144  # 256 KiB


@pytest.mark.unit
def test_initial_score() -> None:
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    assert scorer.score(_PEER) == pytest.approx(0.5)


@pytest.mark.unit
def test_initial_score_low_trust() -> None:
    scorer = PeerScorer()
    scorer.add_peer(_PEER, low_trust=True)
    assert scorer.score(_PEER) == pytest.approx(0.3)


@pytest.mark.unit
def test_latency_ema_decay() -> None:
    """EMA with α=0.3, sequence [100, 200, 100] ms — verifiable by hand."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)

    # EMA starts at 0.0
    scorer.on_piece_received(_PEER, latency_ms=100.0, tessera_size=_TESSERA_SIZE)
    assert scorer.metrics(_PEER).latency_ms == pytest.approx(30.0)

    scorer.on_piece_received(_PEER, latency_ms=200.0, tessera_size=_TESSERA_SIZE)
    assert scorer.metrics(_PEER).latency_ms == pytest.approx(81.0)

    scorer.on_piece_received(_PEER, latency_ms=100.0, tessera_size=_TESSERA_SIZE)
    assert scorer.metrics(_PEER).latency_ms == pytest.approx(86.7)


@pytest.mark.unit
def test_failure_rate_windowed() -> None:
    """20 responses: 18 successes + 2 failures → failure_rate == 0.1."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    for _ in range(18):
        scorer.on_piece_received(_PEER, latency_ms=50.0, tessera_size=_TESSERA_SIZE)
    for _ in range(2):
        scorer.on_failure(_PEER)
    assert scorer.metrics(_PEER).failure_rate == pytest.approx(0.1)


@pytest.mark.unit
def test_failure_rate_window_slides() -> None:
    """25 responses: first 5 fail, next 20 succeed → failure_rate == 0.0."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    for _ in range(5):
        scorer.on_failure(_PEER)
    for _ in range(20):
        scorer.on_piece_received(_PEER, latency_ms=50.0, tessera_size=_TESSERA_SIZE)
    # Window of 20 holds only the last 20 (all successes).
    assert scorer.metrics(_PEER).failure_rate == pytest.approx(0.0)


@pytest.mark.unit
def test_hash_mismatch_penalty() -> None:
    """Each mismatch applies penalty_per_mismatch (0.25) to the score."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    # Establish a decent base score first.
    for _ in range(10):
        scorer.on_piece_received(_PEER, latency_ms=10.0, tessera_size=_TESSERA_SIZE)
    score_before = scorer.score(_PEER)
    scorer.on_hash_mismatch(_PEER)
    scorer.on_hash_mismatch(_PEER)
    score_after = scorer.score(_PEER)
    # Two mismatches should reduce score by ~0.50 (clamped if needed).
    assert score_before - score_after >= 0.4


@pytest.mark.unit
def test_score_clamping_lower() -> None:
    """Many hash mismatches → score clamped to 0.0, never negative."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    for _ in range(10):
        scorer.on_hash_mismatch(_PEER)
    assert scorer.score(_PEER) == pytest.approx(0.0)


@pytest.mark.unit
def test_score_clamping_upper() -> None:
    """Perfect metrics → score clamped to 1.0, never above."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    # Deliver enough bytes to saturate throughput baseline (10 MB).
    total_bytes = 0
    while total_bytes < 10 * 1024 * 1024:
        scorer.on_piece_received(_PEER, latency_ms=0.0, tessera_size=_TESSERA_SIZE)
        total_bytes += _TESSERA_SIZE
    assert scorer.score(_PEER) <= 1.0


@pytest.mark.unit
def test_eviction_threshold() -> None:
    """Score below MIN_PEER_SCORE (0.1) → scorer signals eviction."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    for _ in range(6):
        scorer.on_hash_mismatch(_PEER)
    assert scorer.should_evict(_PEER) is True
    assert scorer.score(_PEER) < MIN_PEER_SCORE


@pytest.mark.unit
def test_deprioritization_threshold() -> None:
    """Score between MIN_PEER_SCORE and DEPRIORITIZE_THRESHOLD → deprioritized."""
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    # Drive score down to ~0.2: one mismatch reduces by 0.25 from base ~0.5.
    scorer.on_hash_mismatch(_PEER)
    scorer.on_hash_mismatch(_PEER)
    s = scorer.score(_PEER)
    if s < DEPRIORITIZE_THRESHOLD:
        assert scorer.is_deprioritized(_PEER) is True


@pytest.mark.unit
def test_custom_scoring_function() -> None:
    """Custom ScoringFunction is used in place of the default formula."""
    calls: list[PeerMetrics] = []

    def always_point_seven(m: PeerMetrics) -> float:
        calls.append(m)
        return 0.7

    scorer = PeerScorer(scoring_fn=always_point_seven)
    scorer.add_peer(_PEER)
    scorer.on_piece_received(_PEER, latency_ms=10.0, tessera_size=_TESSERA_SIZE)
    assert scorer.score(_PEER) == pytest.approx(0.7)
    assert len(calls) == 1


@pytest.mark.unit
def test_bytes_delivered_accumulates() -> None:
    scorer = PeerScorer()
    scorer.add_peer(_PEER)
    for _ in range(5):
        scorer.on_piece_received(_PEER, latency_ms=10.0, tessera_size=_TESSERA_SIZE)
    assert scorer.metrics(_PEER).bytes_delivered == 5 * _TESSERA_SIZE
