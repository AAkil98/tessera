"""Reserved metadata key conventions for agent data exchange.

Spec: ts-spec-010 §2 (Agent Data Plane additions)

These keys are optional but, when present, must follow the documented
semantics.  Other modules (``list_manifests``, ``watch``) filter on
these keys; using the constants avoids typo-driven bugs.
"""

from __future__ import annotations

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Reserved metadata keys
# ---------------------------------------------------------------------------

NAME: str = "name"
"""Human-readable file or artifact name (auto-populated by ``publish()``)."""

DESCRIPTION: str = "description"
"""Human/AI-readable description used by ``query()`` discovery."""

CHANNEL: str = "channel"
"""Logical grouping or topic (e.g. ``'nlp-pipeline'``)."""

PRODUCER: str = "producer"
"""Identifier of the producing agent or process."""

ARTIFACT_TYPE: str = "artifact_type"
"""Kind of artifact: ``dataset``, ``model``, ``result``, ``config``, ``checkpoint``."""

SUPERSEDES: str = "supersedes"
"""Manifest hash (hex) of the artifact this one replaces."""

DEPENDS_ON: str = "depends_on"
"""Comma-separated manifest hashes this artifact requires."""

CREATED_AT: str = "created_at"
"""ISO 8601 timestamp of artifact creation (auto-populated by ``publish()``)."""

RESERVED_KEYS: frozenset[str] = frozenset(
    {
        NAME,
        DESCRIPTION,
        CHANNEL,
        PRODUCER,
        ARTIFACT_TYPE,
        SUPERSEDES,
        DEPENDS_ON,
        CREATED_AT,
    }
)
"""The complete set of reserved metadata keys."""


def auto_populate(meta: dict[str, str]) -> None:
    """Fill in ``created_at`` if not already present.

    Mutates *meta* in place.
    """
    if CREATED_AT not in meta:
        meta[CREATED_AT] = datetime.now(timezone.utc).isoformat()
