"""Tessera CLI — wraps the public TesseraNode API.

Spec: ts-spec-010 §3

Commands:
  tessera publish <file> [--meta KEY=VALUE ...] [--skip-moderation]
  tessera fetch   <manifest_hash> [--output PATH] [--skip-moderation]
  tessera query   <text> [--max-results N]
  tessera status  [<manifest_hash>]
  tessera cancel  <manifest_hash>

Global options:
  --config PATH    TOML config file
  --data-dir PATH  Storage directory (default: ~/.tessera)
  --bind HOST:PORT MFP bind address
  --tracker URL    Tracker URL (repeatable)
  --log-level STR  debug | info | warning | error
  --json           Machine-readable JSON output
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from tessera import __version__
from tessera.config import TesseraConfig
from tessera.errors import (
    ConfigError,
    IntegrityError,
    ModerationError,
    StarvationError,
    TesseraError,
)
from tessera.node import TesseraNode
from tessera.types import NodeStatus, TransferStatus

# ---------------------------------------------------------------------------
# Exit codes (ts-spec-010 §3)
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_APP_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_IO_ERROR = 3
EXIT_NETWORK_ERROR = 4
EXIT_INTEGRITY_ERROR = 5


def _exit_code_for(exc: Exception) -> int:
    if isinstance(exc, IntegrityError):
        return EXIT_INTEGRITY_ERROR
    if isinstance(exc, StarvationError):
        return EXIT_NETWORK_ERROR
    if isinstance(exc, (FileNotFoundError, PermissionError, OSError)):
        return EXIT_IO_ERROR
    if isinstance(exc, (ModerationError, ConfigError)):
        return EXIT_APP_ERROR
    return EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _emit(obj: Any, *, as_json: bool) -> None:
    """Print *obj* as JSON or a human-readable string."""
    if as_json:
        print(json.dumps(obj), flush=True)
    else:
        if isinstance(obj, str):
            print(obj, flush=True)
        else:
            print(json.dumps(obj, indent=2), flush=True)


def _emit_error(msg: str, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"error": msg}), flush=True)
    else:
        print(f"error: {msg}", file=sys.stderr, flush=True)


def _progress_bar(done: int, total: int, width: int = 25) -> str:
    if total == 0:
        return "[" + " " * width + "] ---%"
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = 100.0 * done / total
    return f"[{bar}] {pct:5.1f}%"


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def _fmt_throughput(bps: float) -> str:
    return _fmt_bytes(int(bps)) + "/s"


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


# ---------------------------------------------------------------------------
# Config construction from parsed args
# ---------------------------------------------------------------------------


def _build_config(args: argparse.Namespace) -> TesseraConfig:
    cfg = TesseraConfig.from_toml(Path(args.config)) if args.config else TesseraConfig()

    overrides: dict[str, Any] = {}
    if getattr(args, "data_dir", None):
        overrides["data_dir"] = Path(args.data_dir)
    if getattr(args, "tracker", None):
        overrides["tracker_urls"] = args.tracker
    if getattr(args, "bind", None):
        host, _, port_str = args.bind.rpartition(":")
        overrides["bind_address"] = host or "0.0.0.0"
        overrides["bind_port"] = int(port_str) if port_str else 0

    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)

    return cfg


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


async def _cmd_publish(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    as_json = args.json

    meta: dict[str, str] = {}
    for kv in getattr(args, "meta", []) or []:
        if "=" not in kv:
            _emit_error(f"--meta must be KEY=VALUE, got: {kv!r}", as_json=as_json)
            return EXIT_USAGE_ERROR
        k, _, v = kv.partition("=")
        meta[k] = v

    file_path = Path(args.file)
    if not file_path.exists():
        _emit_error(f"file not found: {file_path}", as_json=as_json)
        return EXIT_IO_ERROR

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, OSError):
            loop.add_signal_handler(sig, _handle_signal)

    try:
        async with TesseraNode(cfg) as node:
            mh = await node.publish(
                file_path,
                metadata=meta or None,
                skip_moderation=getattr(args, "skip_moderation", False),
            )
            mh_hex = mh.hex()
            if as_json:
                _emit({"manifest_hash": mh_hex, "status": "seeding"}, as_json=True)
            else:
                print(f"Published: {mh_hex}")
                print("Seeding. Press Ctrl-C to stop.")
            await stop_event.wait()
    except ModerationError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR
    except (FileNotFoundError, PermissionError, OSError) as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_IO_ERROR
    except TesseraError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR

    return EXIT_OK


async def _cmd_fetch(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    as_json = args.json

    try:
        mh = bytes.fromhex(args.manifest_hash)
    except ValueError:
        _emit_error(
            f"invalid manifest hash (must be 64 hex chars): {args.manifest_hash!r}",
            as_json=as_json,
        )
        return EXIT_USAGE_ERROR

    output_path = Path(args.output) if getattr(args, "output", None) else None

    def on_progress(status: TransferStatus) -> None:
        if as_json:
            _emit(
                {
                    "event": "progress",
                    "pieces_done": status.tesserae_verified,
                    "pieces_total": status.tesserae_total,
                    "throughput_bps": int(status.throughput_bps),
                },
                as_json=True,
            )
        else:
            bar = _progress_bar(status.tesserae_verified, status.tesserae_total)
            tput = _fmt_throughput(status.throughput_bps)
            eta = _fmt_eta(status.eta_seconds)
            print(f"\r{bar}  {tput}  ETA {eta}", end="", flush=True)

    try:
        async with TesseraNode(cfg) as node:
            if not as_json:
                name = args.manifest_hash[:16] + "..."
                print(f"Fetching: {name}")

            out = await node.fetch(
                mh,
                output_path=output_path,
                skip_moderation=getattr(args, "skip_moderation", False),
                on_progress=on_progress,
            )

            if as_json:
                _emit(
                    {"event": "complete", "path": str(out), "size": out.stat().st_size},
                    as_json=True,
                )
            else:
                print()  # end progress line
                size = _fmt_bytes(out.stat().st_size)
                print(f"Complete: {out} ({size}, SHA-256 verified)")
    except IntegrityError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_INTEGRITY_ERROR
    except StarvationError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_NETWORK_ERROR
    except ModerationError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR
    except (FileNotFoundError, PermissionError, OSError) as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_IO_ERROR
    except TesseraError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR

    return EXIT_OK


async def _cmd_query(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    as_json = args.json
    max_results = getattr(args, "max_results", 10)

    try:
        async with TesseraNode(cfg) as node:
            results = await node.query(args.text, max_results=max_results)
    except TesseraError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR

    if as_json:
        _emit(
            [
                {
                    "manifest_hash": r.manifest_hash.hex(),
                    "name": r.name,
                    "relevance_score": r.relevance_score,
                }
                for r in results
            ],
            as_json=True,
        )
    else:
        if not results:
            print("No results.")
        else:
            print(f"  #  {'Score':>5}  {'Hash':<20}  Name")
            for i, r in enumerate(results, 1):
                h = r.manifest_hash.hex()[:16] + "..."
                print(f"  {i:<2} {r.relevance_score:>5.2f}  {h:<20}  {r.name}")

    return EXIT_OK


async def _cmd_status(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    as_json = args.json
    mh_arg = getattr(args, "manifest_hash", None)

    mh: bytes | None = None
    if mh_arg:
        try:
            mh = bytes.fromhex(mh_arg)
        except ValueError:
            _emit_error(f"invalid manifest hash: {mh_arg!r}", as_json=as_json)
            return EXIT_USAGE_ERROR

    try:
        async with TesseraNode(cfg) as node:
            result = await node.status(mh)
    except KeyError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR
    except TesseraError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR

    if as_json:
        if isinstance(result, NodeStatus):
            _emit(
                {
                    "active_swarms": result.active_swarms,
                    "capacity_remaining": result.capacity_remaining,
                    "ai_active": result.ai.active if result.ai else False,
                },
                as_json=True,
            )
        elif isinstance(result, list):
            _emit(
                [_status_dict(s) for s in result],
                as_json=True,
            )
        else:
            assert isinstance(result, TransferStatus)
            _emit(_status_dict(result), as_json=True)
    else:
        if isinstance(result, NodeStatus):
            print(
                f"Active swarms: {result.active_swarms} / "
                f"{result.active_swarms + result.capacity_remaining}"
            )
            if result.ai:
                ai_s = "active" if result.ai.active else "inactive"
                print(f"AI:            {ai_s}")
        elif isinstance(result, list):
            if not result:
                print("No active swarms.")
            else:
                print(
                    f"{'Hash':<20}  {'State':<10}  {'Progress':>10}  {'Peers':>5}  Throughput"
                )
                for s in result:
                    h = s.manifest_hash.hex()[:16] + "..."
                    pct = f"{s.progress * 100:.1f}%"
                    tput = _fmt_throughput(s.throughput_bps)
                    print(
                        f"{h:<20}  {s.state.name:<10}  {pct:>10}  {len(s.peers):>5}  {tput}"
                    )
        else:
            assert isinstance(result, TransferStatus)
            s = result
            progress_pct = s.progress * 100
            print(f"Mosaic:     {s.manifest_hash.hex()[:16]}...")
            print(f"State:      {s.state.name}")
            print(
                f"Progress:   {s.tesserae_verified} / {s.tesserae_total} ({progress_pct:.1f}%)"
            )
            print(f"Peers:      {len(s.peers)}")
            print(f"Throughput: {_fmt_throughput(s.throughput_bps)}")
            print(f"ETA:        {_fmt_eta(s.eta_seconds)}")

    return EXIT_OK


def _status_dict(s: TransferStatus) -> dict[str, Any]:
    return {
        "manifest_hash": s.manifest_hash.hex(),
        "state": s.state.name,
        "progress": s.progress,
        "pieces_done": s.tesserae_verified,
        "pieces_total": s.tesserae_total,
        "throughput_bps": int(s.throughput_bps),
    }


async def _cmd_cancel(args: argparse.Namespace) -> int:
    cfg = _build_config(args)
    as_json = args.json

    try:
        mh = bytes.fromhex(args.manifest_hash)
    except ValueError:
        _emit_error(f"invalid manifest hash: {args.manifest_hash!r}", as_json=as_json)
        return EXIT_USAGE_ERROR

    try:
        async with TesseraNode(cfg) as node:
            if not as_json:
                print(
                    f"Cancelling {args.manifest_hash[:16]}... — draining in-flight pieces..."
                )
            await node.cancel(mh)
            if as_json:
                _emit(
                    {"manifest_hash": args.manifest_hash, "status": "cancelled"},
                    as_json=True,
                )
            else:
                print("Cancelled.")
    except TesseraError as exc:
        _emit_error(str(exc), as_json=as_json)
        return EXIT_APP_ERROR

    return EXIT_OK


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tessera",
        description="Secure peer-to-peer file sharing",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tessera {__version__}",
    )

    # Global options
    parser.add_argument("--config", metavar="PATH", help="TOML config file")
    parser.add_argument(
        "--data-dir", metavar="PATH", help="Storage root (default: ~/.tessera)"
    )
    parser.add_argument("--bind", metavar="HOST:PORT", help="MFP bind address")
    parser.add_argument(
        "--tracker", metavar="URL", action="append", help="Tracker URL (repeatable)"
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Logging verbosity",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON"
    )

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    # publish
    p_pub = sub.add_parser("publish", help="Publish a file and begin seeding")
    p_pub.add_argument("file", metavar="FILE", help="Path to the file to publish")
    p_pub.add_argument(
        "--meta",
        metavar="KEY=VALUE",
        action="append",
        help="Metadata key=value pair (repeatable)",
    )
    p_pub.add_argument("--skip-moderation", action="store_true")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Download a mosaic by manifest hash")
    p_fetch.add_argument(
        "manifest_hash", metavar="HASH", help="64-char hex manifest hash"
    )
    p_fetch.add_argument("--output", metavar="PATH", help="Output file path")
    p_fetch.add_argument("--skip-moderation", action="store_true")

    # query
    p_query = sub.add_parser(
        "query", help="Natural-language mosaic search (requires AI)"
    )
    p_query.add_argument("text", metavar="TEXT", help="Search query")
    p_query.add_argument("--max-results", type=int, default=10, metavar="N")

    # status
    p_status = sub.add_parser("status", help="Show transfer or node status")
    p_status.add_argument(
        "manifest_hash",
        nargs="?",
        metavar="HASH",
        help="Optional: hex manifest hash for a specific mosaic",
    )

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel an active transfer")
    p_cancel.add_argument(
        "manifest_hash", metavar="HASH", help="64-char hex manifest hash"
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMANDS = {
    "publish": _cmd_publish,
    "fetch": _cmd_fetch,
    "query": _cmd_query,
    "status": _cmd_status,
    "cancel": _cmd_cancel,
}


def main() -> None:
    """Entry point for the ``tessera`` command."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(levelname)s %(name)s: %(message)s",
    )

    cmd = _COMMANDS[args.command]
    try:
        exit_code = asyncio.run(cmd(args))
    except KeyboardInterrupt:
        sys.exit(EXIT_OK)
    except SystemExit as exc:
        raise exc
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        sys.exit(EXIT_APP_ERROR)

    sys.exit(exit_code)
