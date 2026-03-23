"""Unit tests for TesseraConfig — ts-spec-013 §3.8."""

from __future__ import annotations

from pathlib import Path

import pytest

from tessera.config import TesseraConfig
from tessera.errors import ConfigError


@pytest.mark.unit
def test_defaults() -> None:
    cfg = TesseraConfig()
    assert cfg.tessera_size == 262_144
    assert cfg.max_peers_per_swarm == 50
    assert cfg.max_swarms_per_node == 10
    assert cfg.eviction_threshold == pytest.approx(0.2)
    assert cfg.starvation_timeout == pytest.approx(120.0)
    assert cfg.max_requests_per_peer == 5
    assert cfg.max_requests_per_swarm == 20
    assert cfg.request_timeout == pytest.approx(30.0)
    assert cfg.score_weight_latency == pytest.approx(0.3)
    assert cfg.score_weight_failure == pytest.approx(0.4)
    assert cfg.score_weight_throughput == pytest.approx(0.3)
    assert cfg.discovery_backends == ["tracker"]
    assert cfg.tracker_urls == []
    assert cfg.ai_enabled is True


@pytest.mark.unit
def test_constructor_override() -> None:
    cfg = TesseraConfig(tessera_size=65_536)
    assert cfg.tessera_size == 65_536


@pytest.mark.unit
def test_invalid_tessera_size_zero() -> None:
    with pytest.raises(ConfigError, match="tessera_size"):
        TesseraConfig(tessera_size=0)


@pytest.mark.unit
def test_tessera_size_exceeds_payload() -> None:
    with pytest.raises(ConfigError, match="tessera_size"):
        TesseraConfig(tessera_size=1_048_572, max_payload_size=1_048_576)


@pytest.mark.unit
def test_tessera_size_at_limit() -> None:
    """tessera_size + 5 == max_payload_size → valid."""
    TesseraConfig(tessera_size=1_048_571, max_payload_size=1_048_576)


@pytest.mark.unit
def test_invalid_score_weights_wrong_sum() -> None:
    with pytest.raises(ConfigError, match="score_weight"):
        TesseraConfig(
            score_weight_latency=0.5,
            score_weight_failure=0.4,
            score_weight_throughput=0.3,  # sum = 1.2
        )


@pytest.mark.unit
def test_invalid_score_weights_negative() -> None:
    with pytest.raises(ConfigError):
        TesseraConfig(
            score_weight_latency=-0.1,
            score_weight_failure=0.7,
            score_weight_throughput=0.4,
        )


@pytest.mark.unit
def test_invalid_thresholds() -> None:
    """score_min > eviction_threshold → ConfigError."""
    with pytest.raises(ConfigError, match="score_min"):
        TesseraConfig(score_min=0.5, eviction_threshold=0.2)


@pytest.mark.unit
def test_toml_override(tmp_path: Path) -> None:
    toml = tmp_path / "tessera.toml"
    toml.write_text("[chunking]\ntessera_size = 131072\n")
    cfg = TesseraConfig.from_toml(toml)
    assert cfg.tessera_size == 131_072


@pytest.mark.unit
def test_toml_data_dir(tmp_path: Path) -> None:
    toml = tmp_path / "tessera.toml"
    toml.write_text('data_dir = "/tmp/tessera-test"\n')
    cfg = TesseraConfig.from_toml(toml)
    assert isinstance(cfg.data_dir, Path)
    assert str(cfg.data_dir) == "/tmp/tessera-test"


@pytest.mark.unit
def test_toml_scoring_section(tmp_path: Path) -> None:
    toml = tmp_path / "tessera.toml"
    toml.write_text(
        "[scoring]\n"
        "weight_latency = 0.5\n"
        "weight_failure = 0.3\n"
        "weight_throughput = 0.2\n"
    )
    cfg = TesseraConfig.from_toml(toml)
    assert cfg.score_weight_latency == pytest.approx(0.5)
    assert cfg.score_weight_failure == pytest.approx(0.3)
    assert cfg.score_weight_throughput == pytest.approx(0.2)


@pytest.mark.unit
def test_toml_unknown_keys_ignored(tmp_path: Path) -> None:
    """Unknown keys in TOML are silently ignored."""
    toml = tmp_path / "tessera.toml"
    toml.write_text("unknown_future_key = 42\n")
    cfg = TesseraConfig.from_toml(toml)
    assert cfg.tessera_size == 262_144  # default unchanged


@pytest.mark.unit
def test_constructor_wins_over_toml(tmp_path: Path) -> None:
    """Constructor kwargs override TOML values."""
    toml = tmp_path / "tessera.toml"
    toml.write_text("[chunking]\ntessera_size = 131072\n")
    cfg = TesseraConfig.from_toml(toml, tessera_size=65_536)
    assert cfg.tessera_size == 65_536
