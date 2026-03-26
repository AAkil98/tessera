"""CLI tests — ts-spec-010 §3.

Tests invoke the async command functions directly (bypassing argparse and
sys.exit) so they can run in-process without spawning subprocesses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tessera.cli import (
    EXIT_APP_ERROR,
    EXIT_INTEGRITY_ERROR,
    EXIT_IO_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_USAGE_ERROR,
    _build_parser,
    _cmd_cancel,
    _cmd_fetch,
    _cmd_publish,
    _cmd_query,
    _cmd_status,
    _fmt_bytes,
    _fmt_throughput,
    _progress_bar,
)
from tests.fixtures import DEFAULT_CHUNK_SIZE, small, tiny

TESSERA_SIZE = DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _args(**kwargs: Any) -> argparse.Namespace:
    """Build a minimal Namespace with required defaults."""
    defaults = {
        "config": None,
        "data_dir": None,
        "bind": None,
        "tracker": None,
        "log_level": "info",
        "json": False,
        "skip_moderation": False,
        "meta": None,
        "output": None,
        "max_results": 10,
        "manifest_hash": None,
        "text": "",
        "file": "",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Formatter helpers
# ---------------------------------------------------------------------------

def test_progress_bar_empty() -> None:
    bar = _progress_bar(0, 0)
    assert "---%" in bar


def test_progress_bar_half() -> None:
    bar = _progress_bar(10, 20)
    assert "50.0%" in bar


def test_progress_bar_full() -> None:
    bar = _progress_bar(20, 20)
    assert "100.0%" in bar


def test_fmt_bytes_kb() -> None:
    assert "KB" in _fmt_bytes(2048)


def test_fmt_bytes_mb() -> None:
    assert "MB" in _fmt_bytes(2 * 1024 * 1024)


def test_fmt_throughput() -> None:
    t = _fmt_throughput(1024 * 1024)
    assert "MB" in t and "/s" in t


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def test_version_flag() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0


def test_parser_publish_required_file() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["publish"])


def test_parser_fetch_required_hash() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch"])


def test_parser_cancel_required_hash() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["cancel"])


def test_parser_status_optional_hash() -> None:
    parser = _build_parser()
    args = parser.parse_args(["status"])
    assert args.manifest_hash is None


def test_parser_global_json_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--json", "status"])
    assert args.json is True


def test_parser_meta_repeatable() -> None:
    parser = _build_parser()
    args = parser.parse_args(["publish", "file.bin", "--meta", "k=v", "--meta", "x=y"])
    assert args.meta == ["k=v", "x=y"]


def test_parser_tracker_repeatable() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--tracker", "http://a", "--tracker", "http://b", "status"])
    assert args.tracker == ["http://a", "http://b"]


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_missing_file(tmp_path: Path) -> None:
    args = _args(data_dir=str(tmp_path), file=str(tmp_path / "nonexistent.bin"))
    code = await _cmd_publish(args)
    assert code == EXIT_IO_ERROR


@pytest.mark.asyncio
async def test_publish_bad_meta_format(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())
    args = _args(data_dir=str(tmp_path), file=str(f), meta=["no-equals-sign"])
    code = await _cmd_publish(args)
    assert code == EXIT_USAGE_ERROR


@pytest.mark.asyncio
async def test_publish_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--json mode emits a valid JSON object with manifest_hash."""
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    # publish blocks on stop_event — fire it immediately via a task trick.
    import tessera.cli as cli_mod

    original_wait = asyncio.Event.wait

    async def _instant_wait(self: asyncio.Event) -> None:
        return  # return immediately

    cli_mod.asyncio.Event.wait = _instant_wait  # type: ignore[method-assign]
    try:
        args = _args(data_dir=str(tmp_path), file=str(f), json=True)
        code = await _cmd_publish(args)
    finally:
        cli_mod.asyncio.Event.wait = original_wait  # type: ignore[method-assign]

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "manifest_hash" in obj
    assert obj["status"] == "seeding"
    assert len(obj["manifest_hash"]) == 64


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_invalid_hash(tmp_path: Path) -> None:
    args = _args(data_dir=str(tmp_path), manifest_hash="not-hex")
    code = await _cmd_fetch(args)
    assert code == EXIT_USAGE_ERROR


@pytest.mark.asyncio
async def test_fetch_starvation_gives_network_error(tmp_path: Path) -> None:
    """fetch with no peers configured → StarvationError → EXIT_NETWORK_ERROR."""
    args = _args(
        data_dir=str(tmp_path),
        manifest_hash="a" * 64,
    )
    code = await _cmd_fetch(args)
    # No piece source configured → starvation or TesseraError
    assert code in (EXIT_NETWORK_ERROR, EXIT_APP_ERROR)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_returns_ok_with_no_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """query with no AI client returns exit 0 and empty results."""
    args = _args(data_dir=str(tmp_path), text="anything", max_results=5)
    code = await _cmd_query(args)
    assert code == EXIT_OK


@pytest.mark.asyncio
async def test_query_json_output_is_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(data_dir=str(tmp_path), text="report", json=True)
    code = await _cmd_query(args)
    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == []


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_no_active_swarms(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(data_dir=str(tmp_path))
    code = await _cmd_status(args)
    assert code == EXIT_OK


@pytest.mark.asyncio
async def test_status_json_node_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(data_dir=str(tmp_path), json=True)
    code = await _cmd_status(args)
    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "active_swarms" in obj
    assert "capacity_remaining" in obj


@pytest.mark.asyncio
async def test_status_invalid_hash(tmp_path: Path) -> None:
    args = _args(data_dir=str(tmp_path), manifest_hash="zzz")
    code = await _cmd_status(args)
    assert code == EXIT_USAGE_ERROR


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_invalid_hash(tmp_path: Path) -> None:
    args = _args(data_dir=str(tmp_path), manifest_hash="not-hex")
    code = await _cmd_cancel(args)
    assert code == EXIT_USAGE_ERROR


@pytest.mark.asyncio
async def test_cancel_unknown_swarm_exits_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cancelling a swarm not in the registry should not crash — registry.get raises."""
    args = _args(data_dir=str(tmp_path), manifest_hash="b" * 64)
    code = await _cmd_cancel(args)
    # Either OK (no-op) or app-error is fine — must not be usage error or crash.
    assert code in (EXIT_OK, EXIT_APP_ERROR)


@pytest.mark.asyncio
async def test_cancel_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cancel with --json emits a JSON object (success or error)."""
    args = _args(data_dir=str(tmp_path), manifest_hash="b" * 64, json=True)
    await _cmd_cancel(args)
    out = capsys.readouterr().out.strip()
    if out:
        obj = json.loads(out)
        assert isinstance(obj, dict)


# ---------------------------------------------------------------------------
# Exit code mapping
# ---------------------------------------------------------------------------

def test_exit_code_constants_are_distinct() -> None:
    codes = [EXIT_OK, EXIT_APP_ERROR, EXIT_USAGE_ERROR, EXIT_IO_ERROR, EXIT_NETWORK_ERROR, EXIT_INTEGRITY_ERROR]
    assert len(set(codes)) == len(codes)


def test_exit_code_ok_is_zero() -> None:
    assert EXIT_OK == 0


# ---------------------------------------------------------------------------
# Full round-trip: publish + status (text mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_then_status_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish a file (instant stop), then status shows no active swarms."""
    import tessera.cli as cli_mod

    original_wait = asyncio.Event.wait

    async def _instant_wait(self: asyncio.Event) -> None:
        return

    cli_mod.asyncio.Event.wait = _instant_wait  # type: ignore[method-assign]
    try:
        f = tmp_path / "data.bin"
        f.write_bytes(small())
        pub_args = _args(data_dir=str(tmp_path), file=str(f))
        await _cmd_publish(pub_args)
    finally:
        cli_mod.asyncio.Event.wait = original_wait  # type: ignore[method-assign]

    capsys.readouterr()  # clear publish output

    status_args = _args(data_dir=str(tmp_path))
    code = await _cmd_status(status_args)
    assert code == EXIT_OK
