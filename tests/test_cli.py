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
    _build_config,
    _build_parser,
    _cmd_cancel,
    _cmd_fetch,
    _cmd_publish,
    _cmd_query,
    _cmd_status,
    _emit,
    _emit_error,
    _exit_code_for,
    _fmt_bytes,
    _fmt_eta,
    _fmt_throughput,
    _progress_bar,
)
from tessera.errors import ConfigError, IntegrityError, ModerationError, StarvationError
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
    args = parser.parse_args(
        ["--tracker", "http://a", "--tracker", "http://b", "status"]
    )
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
async def test_publish_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    codes = [
        EXIT_OK,
        EXIT_APP_ERROR,
        EXIT_USAGE_ERROR,
        EXIT_IO_ERROR,
        EXIT_NETWORK_ERROR,
        EXIT_INTEGRITY_ERROR,
    ]
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


# ---------------------------------------------------------------------------
# _fmt_bytes — additional ranges
# ---------------------------------------------------------------------------


def test_fmt_bytes_small_value() -> None:
    """Values under 1024 should display in bytes."""
    result = _fmt_bytes(512)
    assert "B" in result
    assert "KB" not in result


def test_fmt_bytes_zero() -> None:
    result = _fmt_bytes(0)
    assert result == "0.0 B"


def test_fmt_bytes_gb() -> None:
    result = _fmt_bytes(2 * 1024 * 1024 * 1024)
    assert "GB" in result


def test_fmt_bytes_tb() -> None:
    result = _fmt_bytes(3 * 1024 * 1024 * 1024 * 1024)
    assert "TB" in result


def test_fmt_bytes_exact_boundary_kb() -> None:
    """Exactly 1024 bytes should roll over to KB."""
    result = _fmt_bytes(1024)
    assert "KB" in result


# ---------------------------------------------------------------------------
# _fmt_eta
# ---------------------------------------------------------------------------


def test_fmt_eta_none_returns_question_mark() -> None:
    assert _fmt_eta(None) == "?"


def test_fmt_eta_seconds_below_minute() -> None:
    assert _fmt_eta(45) == "45s"


def test_fmt_eta_zero_seconds() -> None:
    assert _fmt_eta(0) == "0s"


def test_fmt_eta_exact_one_minute() -> None:
    assert _fmt_eta(60) == "1m00s"


def test_fmt_eta_minutes_and_seconds() -> None:
    assert _fmt_eta(125) == "2m05s"


def test_fmt_eta_large_value() -> None:
    result = _fmt_eta(3661)
    assert result == "61m01s"


# ---------------------------------------------------------------------------
# _exit_code_for
# ---------------------------------------------------------------------------


def test_exit_code_for_integrity_error() -> None:
    exc = IntegrityError(b"\x00" * 32, b"\x01" * 32, b"\x02" * 32)
    assert _exit_code_for(exc) == EXIT_INTEGRITY_ERROR


def test_exit_code_for_starvation_error() -> None:
    exc = StarvationError(b"\x00" * 32, elapsed=30.0)
    assert _exit_code_for(exc) == EXIT_NETWORK_ERROR


def test_exit_code_for_file_not_found() -> None:
    assert _exit_code_for(FileNotFoundError("missing")) == EXIT_IO_ERROR


def test_exit_code_for_permission_error() -> None:
    assert _exit_code_for(PermissionError("denied")) == EXIT_IO_ERROR


def test_exit_code_for_os_error() -> None:
    assert _exit_code_for(OSError("disk")) == EXIT_IO_ERROR


def test_exit_code_for_moderation_error() -> None:
    exc = ModerationError("blocked")
    assert _exit_code_for(exc) == EXIT_APP_ERROR


def test_exit_code_for_config_error() -> None:
    exc = ConfigError("field", "bad value")
    assert _exit_code_for(exc) == EXIT_APP_ERROR


def test_exit_code_for_generic_exception_falls_back() -> None:
    """Any unrecognised exception should map to EXIT_APP_ERROR."""
    assert _exit_code_for(RuntimeError("oops")) == EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# _emit
# ---------------------------------------------------------------------------


def test_emit_json_mode_dict(capsys: pytest.CaptureFixture[str]) -> None:
    _emit({"key": "value"}, as_json=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"key": "value"}


def test_emit_json_mode_list(capsys: pytest.CaptureFixture[str]) -> None:
    _emit([1, 2, 3], as_json=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == [1, 2, 3]


def test_emit_text_mode_string(capsys: pytest.CaptureFixture[str]) -> None:
    _emit("hello world", as_json=False)
    out = capsys.readouterr().out.strip()
    assert out == "hello world"


def test_emit_text_mode_dict_pretty(capsys: pytest.CaptureFixture[str]) -> None:
    """Non-JSON mode with a dict should pretty-print with indent."""
    _emit({"a": 1}, as_json=False)
    out = capsys.readouterr().out
    # Pretty-printed JSON has newlines and indentation
    assert "\n" in out
    assert json.loads(out) == {"a": 1}


# ---------------------------------------------------------------------------
# _emit_error
# ---------------------------------------------------------------------------


def test_emit_error_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_error("something broke", as_json=True)
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert obj == {"error": "something broke"}


def test_emit_error_text_mode(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_error("something broke", as_json=False)
    err = capsys.readouterr().err.strip()
    assert "error:" in err
    assert "something broke" in err


# ---------------------------------------------------------------------------
# _build_config
# ---------------------------------------------------------------------------


def test_build_config_defaults() -> None:
    """With no overrides, _build_config returns a default TesseraConfig."""
    args = _args()
    cfg = _build_config(args)
    assert cfg.bind_address == "0.0.0.0"
    assert cfg.bind_port == 0


def test_build_config_data_dir_override(tmp_path: Path) -> None:
    args = _args(data_dir=str(tmp_path))
    cfg = _build_config(args)
    assert cfg.data_dir == tmp_path


def test_build_config_tracker_override() -> None:
    args = _args(tracker=["http://tracker1", "http://tracker2"])
    cfg = _build_config(args)
    assert cfg.tracker_urls == ["http://tracker1", "http://tracker2"]


def test_build_config_bind_override() -> None:
    args = _args(bind="127.0.0.1:9000")
    cfg = _build_config(args)
    assert cfg.bind_address == "127.0.0.1"
    assert cfg.bind_port == 9000


# ---------------------------------------------------------------------------
# _progress_bar — custom width
# ---------------------------------------------------------------------------


def test_progress_bar_custom_width() -> None:
    bar = _progress_bar(5, 10, width=10)
    assert "50.0%" in bar
    # With width=10, 50% filled -> 5 filled chars
    assert len(bar) > 10
