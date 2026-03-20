"""TesseraConfig — single configuration object for the entire system.

Spec: ts-spec-010 §4

All values referenced as "configurable via ts-spec-010" in other specs
are defined here. Precedence (later wins):
  1. Dataclass defaults
  2. TOML file (TesseraConfig.from_toml)
  3. Direct constructor arguments
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from tessera.errors import ConfigError

# ---------------------------------------------------------------------------
# MFP default payload limit — used to validate tessera_size.
# Must be ≤ MFP RuntimeConfig.max_payload_size (ts-spec-005 §6).
# ---------------------------------------------------------------------------
_DEFAULT_MAX_PAYLOAD: int = 1_048_576  # 1 MB

# TOML section → {toml_key: dataclass_field_name}
_SECTION_MAP: dict[str, dict[str, str]] = {
    "chunking": {
        "tessera_size": "tessera_size",
    },
    "swarm": {
        "max_peers_per_swarm": "max_peers_per_swarm",
        "max_swarms_per_node": "max_swarms_per_node",
        "eviction_threshold": "eviction_threshold",
        "starvation_timeout": "starvation_timeout",
        "starvation_backoff_base": "starvation_backoff_base",
        "starvation_backoff_max": "starvation_backoff_max",
    },
    "transfer": {
        "max_requests_per_peer": "max_requests_per_peer",
        "max_requests_per_swarm": "max_requests_per_swarm",
        "request_timeout": "request_timeout",
        "max_retries_per_tessera": "max_retries_per_tessera",
        "endgame_threshold": "endgame_threshold",
        "max_endgame_requests": "max_endgame_requests",
    },
    "scoring": {
        "weight_latency": "score_weight_latency",
        "weight_failure": "score_weight_failure",
        "weight_throughput": "score_weight_throughput",
        "penalty_mismatch": "score_penalty_mismatch",
        "min": "score_min",
        "deprioritize": "score_deprioritize",
    },
    "discovery": {
        "backends": "discovery_backends",
        "tracker_urls": "tracker_urls",
        "announce_interval": "tracker_announce_interval",
    },
    "ai": {
        "enabled": "ai_enabled",
        "moderation_on_publish": "ai_moderation_on_publish",
        "moderation_on_fetch": "ai_moderation_on_fetch",
        "ranking_interval": "ai_ranking_interval",
        "ranking_confidence_threshold": "ai_ranking_confidence_threshold",
    },
}


@dataclass
class TesseraConfig:
    """Complete Tessera configuration.

    All fields have sensible defaults. Pass to TesseraNode() to override.
    """

    # --- Node identity ---
    data_dir: Path = field(default_factory=lambda: Path("~/.tessera"))
    bind_address: str = "0.0.0.0"
    bind_port: int = 0

    # --- Chunking (ts-spec-006) ---
    tessera_size: int = 262_144
    max_payload_size: int = _DEFAULT_MAX_PAYLOAD

    # --- Swarm management (ts-spec-007) ---
    max_peers_per_swarm: int = 50
    max_swarms_per_node: int = 10
    eviction_threshold: float = 0.2
    starvation_timeout: float = 120.0
    starvation_backoff_base: float = 5.0
    starvation_backoff_max: float = 60.0

    # --- Transfer engine (ts-spec-008) ---
    max_requests_per_peer: int = 5
    max_requests_per_swarm: int = 20
    request_timeout: float = 30.0
    max_retries_per_tessera: int = 10
    endgame_threshold: int = 20
    max_endgame_requests: int = 100

    # --- Peer scoring (ts-spec-008) ---
    score_weight_latency: float = 0.3
    score_weight_failure: float = 0.4
    score_weight_throughput: float = 0.3
    score_penalty_mismatch: float = 0.25
    score_min: float = 0.1
    score_deprioritize: float = 0.3

    # --- Discovery (ts-spec-007) ---
    discovery_backends: list[str] = field(default_factory=lambda: ["tracker"])
    tracker_urls: list[str] = field(default_factory=list)
    tracker_announce_interval: float = 1800.0

    # --- AI integration (ts-spec-009) ---
    ai_enabled: bool = True
    ai_moderation_on_publish: bool = True
    ai_moderation_on_fetch: bool = True
    ai_ranking_interval: float = 60.0
    ai_ranking_confidence_threshold: float = 0.7

    # --- Timeouts and limits ---
    graceful_shutdown_timeout: float = 30.0
    max_metadata_keys: int = 64
    max_metadata_value_bytes: int = 1024

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.tessera_size <= 0:
            raise ConfigError("tessera_size", "must be a positive integer")
        if self.tessera_size + 5 > self.max_payload_size:
            raise ConfigError(
                "tessera_size",
                f"tessera_size ({self.tessera_size}) + 5 exceeds "
                f"max_payload_size ({self.max_payload_size})",
            )
        weight_sum = (
            self.score_weight_latency
            + self.score_weight_failure
            + self.score_weight_throughput
        )
        if abs(weight_sum - 1.0) > 1e-6:
            raise ConfigError(
                "score_weight_*",
                f"latency + failure + throughput weights must sum to 1.0, "
                f"got {weight_sum:.6f}",
            )
        if self.score_weight_latency < 0:
            raise ConfigError("score_weight_latency", "must be non-negative")
        if self.score_weight_failure < 0:
            raise ConfigError("score_weight_failure", "must be non-negative")
        if self.score_weight_throughput < 0:
            raise ConfigError("score_weight_throughput", "must be non-negative")
        if self.score_min > self.eviction_threshold:
            raise ConfigError(
                "score_min",
                f"score_min ({self.score_min}) must not exceed "
                f"eviction_threshold ({self.eviction_threshold})",
            )

    @classmethod
    def from_toml(cls, path: Path, **overrides: Any) -> TesseraConfig:
        """Load config from a TOML file, with optional field overrides.

        Args:
            path: Path to the .toml config file.
            **overrides: Dataclass field names → values that override TOML.

        Returns:
            A new TesseraConfig with TOML values applied, then overrides.
        """
        with open(path, "rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)

        # Build {field_name: value} from the TOML document.
        kwargs: dict[str, Any] = {}
        field_names = {f.name for f in fields(cls)}

        # Top-level keys map directly if they match a field name.
        for key, value in raw.items():
            if isinstance(value, dict):
                continue  # section — handled below
            if key in field_names:
                kwargs[key] = value
            # Unknown top-level scalars are silently ignored.

        # Section keys are translated via _SECTION_MAP.
        for section, mapping in _SECTION_MAP.items():
            if section not in raw or not isinstance(raw[section], dict):
                continue
            section_data: dict[str, Any] = raw[section]
            for toml_key, field_name in mapping.items():
                if toml_key in section_data:
                    kwargs[field_name] = section_data[toml_key]

        # Apply explicit overrides (constructor wins over TOML).
        kwargs.update(overrides)

        # Coerce data_dir to Path if loaded as string.
        if "data_dir" in kwargs and not isinstance(kwargs["data_dir"], Path):
            kwargs["data_dir"] = Path(str(kwargs["data_dir"]))

        return cls(**kwargs)
