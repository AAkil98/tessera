"""Unit tests for tessera.metadata — reserved keys and auto-population."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tessera.metadata import (
    ARTIFACT_TYPE,
    CHANNEL,
    CREATED_AT,
    DEPENDS_ON,
    DESCRIPTION,
    NAME,
    PRODUCER,
    RESERVED_KEYS,
    SUPERSEDES,
    auto_populate,
)


# ===================================================================
# Constant values
# ===================================================================


class TestConstants:
    """Each reserved key constant maps to the expected string."""

    @pytest.mark.unit
    def test_name(self) -> None:
        assert NAME == "name"

    @pytest.mark.unit
    def test_description(self) -> None:
        assert DESCRIPTION == "description"

    @pytest.mark.unit
    def test_channel(self) -> None:
        assert CHANNEL == "channel"

    @pytest.mark.unit
    def test_producer(self) -> None:
        assert PRODUCER == "producer"

    @pytest.mark.unit
    def test_artifact_type(self) -> None:
        assert ARTIFACT_TYPE == "artifact_type"

    @pytest.mark.unit
    def test_supersedes(self) -> None:
        assert SUPERSEDES == "supersedes"

    @pytest.mark.unit
    def test_depends_on(self) -> None:
        assert DEPENDS_ON == "depends_on"

    @pytest.mark.unit
    def test_created_at(self) -> None:
        assert CREATED_AT == "created_at"


# ===================================================================
# RESERVED_KEYS
# ===================================================================


class TestReservedKeys:
    """RESERVED_KEYS frozenset is complete and immutable."""

    @pytest.mark.unit
    def test_is_frozenset(self) -> None:
        assert isinstance(RESERVED_KEYS, frozenset)

    @pytest.mark.unit
    def test_contains_all_constants(self) -> None:
        expected = {
            NAME,
            DESCRIPTION,
            CHANNEL,
            PRODUCER,
            ARTIFACT_TYPE,
            SUPERSEDES,
            DEPENDS_ON,
            CREATED_AT,
        }
        assert RESERVED_KEYS == expected

    @pytest.mark.unit
    def test_count(self) -> None:
        assert len(RESERVED_KEYS) == 8


# ===================================================================
# auto_populate()
# ===================================================================


class TestAutoPopulate:
    """auto_populate() fills created_at when missing."""

    @pytest.mark.unit
    def test_adds_created_at(self) -> None:
        meta: dict[str, str] = {"name": "test.bin"}
        auto_populate(meta)
        assert CREATED_AT in meta

    @pytest.mark.unit
    def test_does_not_overwrite_existing(self) -> None:
        fixed = "2025-01-01T00:00:00+00:00"
        meta: dict[str, str] = {"name": "test.bin", CREATED_AT: fixed}
        auto_populate(meta)
        assert meta[CREATED_AT] == fixed

    @pytest.mark.unit
    def test_timestamp_is_valid_iso8601(self) -> None:
        meta: dict[str, str] = {"name": "test.bin"}
        auto_populate(meta)
        # Must not raise.
        parsed = datetime.fromisoformat(meta[CREATED_AT])
        assert parsed.tzinfo is not None

    @pytest.mark.unit
    def test_timestamp_is_utc(self) -> None:
        meta: dict[str, str] = {"name": "test.bin"}
        auto_populate(meta)
        parsed = datetime.fromisoformat(meta[CREATED_AT])
        assert parsed.tzinfo == timezone.utc

    @pytest.mark.unit
    def test_mutates_in_place(self) -> None:
        """auto_populate returns None and mutates the dict."""
        meta: dict[str, str] = {"name": "x"}
        result = auto_populate(meta)
        assert result is None
        assert CREATED_AT in meta

    @pytest.mark.unit
    def test_does_not_touch_other_keys(self) -> None:
        meta: dict[str, str] = {"name": "x", "channel": "ch1"}
        auto_populate(meta)
        assert meta["name"] == "x"
        assert meta["channel"] == "ch1"
        # Only created_at was added.
        assert set(meta.keys()) == {"name", "channel", CREATED_AT}

    @pytest.mark.unit
    def test_empty_string_created_at_not_overwritten(self) -> None:
        """Even an empty string counts as 'present'."""
        meta: dict[str, str] = {"name": "x", CREATED_AT: ""}
        auto_populate(meta)
        assert meta[CREATED_AT] == ""
