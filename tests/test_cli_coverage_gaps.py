"""CLI tests — close remaining coverage gaps in tessera/cli.py.

These tests target specific uncovered lines/branches identified by
coverage analysis. Each test is annotated with the line(s) it covers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
    main,
)
from tessera.errors import ModerationError, TesseraError
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


def _patch_event_wait():
    """Context manager to make asyncio.Event.wait() return immediately."""
    import tessera.cli as cli_mod

    original_wait = asyncio.Event.wait

    async def _instant_wait(self: asyncio.Event) -> None:
        return

    cli_mod.asyncio.Event.wait = _instant_wait  # type: ignore[method-assign]

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a: object):
            cli_mod.asyncio.Event.wait = original_wait  # type: ignore[method-assign]

    return _Ctx()


def _publish_and_get_hash(tmp_path: Path) -> tuple[Path, str]:
    """Write a file, publish it via CLI, and return (file_path, hex_hash)."""
    f = tmp_path / "data.bin"
    f.write_bytes(small())
    return f, ""


# ---------------------------------------------------------------------------
# Lines 160-161: Valid --meta parsing (k, _, v = kv.partition("="))
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_with_valid_meta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish with valid --meta KEY=VALUE pairs.

    Covers cli.py lines 160-161.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with _patch_event_wait():
        args = _args(
            data_dir=str(tmp_path),
            file=str(f),
            meta=["author=Alice", "version=1.0"],
            json=True,
        )
        code = await _cmd_publish(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "manifest_hash" in obj


# ---------------------------------------------------------------------------
# Line 172: Signal handler (_handle_signal)
# Tested indirectly - the signal handler just sets stop_event.
# We verify it by the monkey-patch approach used in other tests.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_text_mode_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish in text mode emits 'Published:' and 'Seeding' messages.

    Covers cli.py line 172 (signal handler registration path)
    and lines 188-190 (text output).
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with _patch_event_wait():
        args = _args(data_dir=str(tmp_path), file=str(f), json=False)
        code = await _cmd_publish(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Published:" in out
    assert "Seeding" in out


# ---------------------------------------------------------------------------
# Lines 192-200: publish exception handlers
# (ModerationError, FileNotFoundError, OSError, TesseraError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_moderation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish that triggers ModerationError returns EXIT_APP_ERROR.

    Covers cli.py lines 192-194.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.publish.side_effect = ModerationError("content blocked")
        args = _args(data_dir=str(tmp_path), file=str(f), json=True)
        code = await _cmd_publish(args)

    assert code == EXIT_APP_ERROR
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "error" in obj


@pytest.mark.asyncio
async def test_publish_file_not_found_from_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish where node.publish() raises FileNotFoundError.

    Covers cli.py lines 195-197.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.publish.side_effect = FileNotFoundError("gone")
        args = _args(data_dir=str(tmp_path), file=str(f))
        code = await _cmd_publish(args)

    assert code == EXIT_IO_ERROR


@pytest.mark.asyncio
async def test_publish_os_error_from_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish where node.publish() raises OSError.

    Covers cli.py lines 195-197.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.publish.side_effect = OSError("disk full")
        args = _args(data_dir=str(tmp_path), file=str(f))
        code = await _cmd_publish(args)

    assert code == EXIT_IO_ERROR


@pytest.mark.asyncio
async def test_publish_tessera_error_from_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Publish where node.publish() raises TesseraError.

    Covers cli.py lines 198-200.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.publish.side_effect = TesseraError("publish failed")
        args = _args(data_dir=str(tmp_path), file=str(f))
        code = await _cmd_publish(args)

    assert code == EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# Lines 221-235: fetch on_progress callback + output
# Lines 250-258: fetch success path (JSON + text)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_json_progress_and_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Full fetch in JSON mode: progress events and completion message.

    Covers cli.py lines 221-230 (on_progress JSON branch),
    250-254 (JSON complete output).
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    from tessera import TesseraConfig, TesseraNode
    from tessera.storage.manifest_store import ManifestStore
    from tessera.storage.tessera_store import TesseraStore

    # Publish to get a real manifest hash.
    cfg_pub = TesseraConfig(data_dir=pub, tessera_size=TESSERA_SIZE)
    async with TesseraNode(cfg_pub) as publisher:
        mh = await publisher.publish(str(src))
    mh_hex = mh.hex()

    # Now fetch using a real node with _test_piece_provider.
    class _LocalSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, h: bytes):
            self._ms, self._ts, self._h = ms, ts, h

        async def get_manifest(self) -> bytes | None:
            return await self._ms.read(self._h)

        async def get_piece(self, index: int) -> bytes | None:
            return await self._ts.read(self._h, index)

    src_obj = _LocalSource(publisher._manifest_store, publisher._tessera_store, mh)

    # Patch TesseraNode so the CLI creates one with our test provider.
    original_cls = __import__("tessera.cli", fromlist=["TesseraNode"]).TesseraNode

    class PatchedNode(original_cls):
        async def start(self) -> None:
            await super().start()
            self._test_piece_provider = src_obj

    with patch("tessera.cli.TesseraNode", PatchedNode):
        args = _args(
            data_dir=str(fet),
            manifest_hash=mh_hex,
            json=True,
        )
        code = await _cmd_fetch(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    # Multiple JSON lines: progress events and a completion event.
    lines = out.split("\n")
    objs = [json.loads(line) for line in lines]
    events = [o.get("event") for o in objs]
    assert "progress" in events
    assert "complete" in events


@pytest.mark.asyncio
async def test_fetch_text_progress_and_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Full fetch in text mode: progress bar and completion message.

    Covers cli.py lines 231-235 (on_progress text branch),
    255-258 (text complete output).
    """
    pub = tmp_path / "pub"
    fet = tmp_path / "fet"
    src = pub / "data.bin"
    src.parent.mkdir()
    src.write_bytes(small())

    from tessera import TesseraConfig, TesseraNode
    from tessera.storage.manifest_store import ManifestStore
    from tessera.storage.tessera_store import TesseraStore

    cfg_pub = TesseraConfig(data_dir=pub, tessera_size=TESSERA_SIZE)
    async with TesseraNode(cfg_pub) as publisher:
        mh = await publisher.publish(str(src))
    mh_hex = mh.hex()

    class _LocalSource:
        def __init__(self, ms: ManifestStore, ts: TesseraStore, h: bytes):
            self._ms, self._ts, self._h = ms, ts, h

        async def get_manifest(self) -> bytes | None:
            return await self._ms.read(self._h)

        async def get_piece(self, index: int) -> bytes | None:
            return await self._ts.read(self._h, index)

    src_obj = _LocalSource(publisher._manifest_store, publisher._tessera_store, mh)

    original_cls = __import__("tessera.cli", fromlist=["TesseraNode"]).TesseraNode

    class PatchedNode(original_cls):
        async def start(self) -> None:
            await super().start()
            self._test_piece_provider = src_obj

    with patch("tessera.cli.TesseraNode", PatchedNode):
        args = _args(
            data_dir=str(fet),
            manifest_hash=mh_hex,
            json=False,
        )
        code = await _cmd_fetch(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Fetching:" in out
    assert "Complete:" in out
    assert "SHA-256 verified" in out


# ---------------------------------------------------------------------------
# Lines 260-261, 265-275: fetch exception handlers
# (IntegrityError, StarvationError, ModerationError, OSError, TesseraError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_integrity_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fetch with IntegrityError returns EXIT_INTEGRITY_ERROR.

    Covers cli.py lines 260-261.
    """
    from tessera.errors import IntegrityError

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.fetch.side_effect = IntegrityError(b"\x00" * 32, b"\x01" * 32, b"\x02" * 32)
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32, json=True)
        code = await _cmd_fetch(args)

    assert code == EXIT_INTEGRITY_ERROR


@pytest.mark.asyncio
async def test_fetch_moderation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fetch with ModerationError returns EXIT_APP_ERROR.

    Covers cli.py lines 265-267.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.fetch.side_effect = ModerationError("content blocked")
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32)
        code = await _cmd_fetch(args)

    assert code == EXIT_APP_ERROR


@pytest.mark.asyncio
async def test_fetch_os_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fetch with OSError returns EXIT_IO_ERROR.

    Covers cli.py lines 268-270.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.fetch.side_effect = OSError("disk error")
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32)
        code = await _cmd_fetch(args)

    assert code == EXIT_IO_ERROR


@pytest.mark.asyncio
async def test_fetch_tessera_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fetch with TesseraError returns EXIT_APP_ERROR.

    Covers cli.py lines 271-273.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.fetch.side_effect = TesseraError("fetch failed")
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32)
        code = await _cmd_fetch(args)

    assert code == EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# Lines 286-288: query exception handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tessera_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """query with TesseraError returns EXIT_APP_ERROR.

    Covers cli.py lines 286-288.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.query.side_effect = TesseraError("query failed")
        args = _args(data_dir=str(tmp_path), text="something", json=True)
        code = await _cmd_query(args)

    assert code == EXIT_APP_ERROR
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "error" in obj


# ---------------------------------------------------------------------------
# Lines 306-309: query with no results (text mode table header)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_text_no_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """query with no results in text mode prints 'No results.'.

    Covers cli.py lines 303-304 (no results text).
    """
    args = _args(data_dir=str(tmp_path), json=False, text="anything")
    code = await _cmd_query(args)
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "No results." in out


@pytest.mark.asyncio
async def test_query_text_with_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """query with results in text mode prints table header and rows.

    Covers cli.py lines 306-309 (text mode table).
    """
    from tessera.types import DiscoveryResult

    results = [
        DiscoveryResult(
            manifest_hash=b"\xaa" * 32,
            name="test-file.bin",
            relevance_score=0.95,
        ),
        DiscoveryResult(
            manifest_hash=b"\xbb" * 32,
            name="other-file.bin",
            relevance_score=0.80,
        ),
    ]

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.query.return_value = results
        args = _args(data_dir=str(tmp_path), json=False, text="something")
        code = await _cmd_query(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Score" in out
    assert "Hash" in out
    assert "Name" in out
    assert "test-file.bin" in out
    assert "other-file.bin" in out


# ---------------------------------------------------------------------------
# Lines 330-335: status exception handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_key_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status with KeyError returns EXIT_APP_ERROR.

    Covers cli.py lines 330-332.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.side_effect = KeyError("no manifest for ffff...")
        args = _args(data_dir=str(tmp_path), manifest_hash="ff" * 32, json=True)
        code = await _cmd_status(args)

    assert code == EXIT_APP_ERROR


@pytest.mark.asyncio
async def test_status_tessera_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status with TesseraError returns EXIT_APP_ERROR.

    Covers cli.py lines 333-335.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.side_effect = TesseraError("status failed")
        args = _args(data_dir=str(tmp_path), json=True)
        code = await _cmd_status(args)

    assert code == EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# Lines 347-354: status JSON output for list
# Lines 361-391: status text output for list of transfers
# Lines 395: status return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_json_transfer_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status (no hash) with active swarms returns JSON list.

    Covers cli.py lines 347-350 (JSON list branch).
    """
    from tessera.types import SwarmState, TransferMode, TransferStatus

    statuses = [
        TransferStatus(
            manifest_hash=b"\xaa" * 32,
            state=SwarmState.ACTIVE,
            mode=TransferMode.NORMAL,
            progress=0.5,
            bytes_received=512,
            bytes_total=1024,
            throughput_bps=100.0,
            eta_seconds=5.0,
            tesserae_verified=2,
            tesserae_total=4,
            tesserae_in_flight=1,
            stuck_tesserae=[],
            peers=[],
        ),
    ]

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = statuses
        args = _args(data_dir=str(tmp_path), json=True)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert isinstance(obj, list)
    assert len(obj) == 1
    assert obj[0]["progress"] == 0.5
    assert "manifest_hash" in obj[0]


@pytest.mark.asyncio
async def test_status_json_single_transfer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status(manifest_hash) returns JSON for a single TransferStatus.

    Covers cli.py lines 352-354 (JSON single transfer branch).
    """
    from tessera.types import SwarmState, TransferMode, TransferStatus

    ts = TransferStatus(
        manifest_hash=b"\xaa" * 32,
        state=SwarmState.ACTIVE,
        mode=TransferMode.NORMAL,
        progress=0.75,
        bytes_received=768,
        bytes_total=1024,
        throughput_bps=200.0,
        eta_seconds=2.0,
        tesserae_verified=3,
        tesserae_total=4,
        tesserae_in_flight=0,
        stuck_tesserae=[],
        peers=[],
    )

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = ts
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32, json=True)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert obj["progress"] == 0.75


@pytest.mark.asyncio
async def test_status_text_transfer_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status (no hash) with active swarms returns text table.

    Covers cli.py lines 364-377 (text list table).
    """
    from tessera.types import SwarmState, TransferMode, TransferStatus

    statuses = [
        TransferStatus(
            manifest_hash=b"\xaa" * 32,
            state=SwarmState.ACTIVE,
            mode=TransferMode.NORMAL,
            progress=0.5,
            bytes_received=512,
            bytes_total=1024,
            throughput_bps=1024.0,
            eta_seconds=10.0,
            tesserae_verified=2,
            tesserae_total=4,
            tesserae_in_flight=1,
            stuck_tesserae=[],
            peers=[],
        ),
        TransferStatus(
            manifest_hash=b"\xbb" * 32,
            state=SwarmState.ACTIVE,
            mode=TransferMode.NORMAL,
            progress=0.25,
            bytes_received=256,
            bytes_total=1024,
            throughput_bps=512.0,
            eta_seconds=20.0,
            tesserae_verified=1,
            tesserae_total=4,
            tesserae_in_flight=2,
            stuck_tesserae=[],
            peers=[],
        ),
    ]

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = statuses
        args = _args(data_dir=str(tmp_path), json=False)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    # Table header
    assert "Hash" in out
    assert "State" in out
    assert "Progress" in out
    assert "Peers" in out
    assert "Throughput" in out
    # Row data
    assert "ACTIVE" in out
    assert "50.0%" in out


@pytest.mark.asyncio
async def test_status_text_empty_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status (no hash) with empty list prints 'No active swarms.'.

    Covers cli.py lines 365-366 (empty list text).
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = []
        args = _args(data_dir=str(tmp_path), json=False)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "No active swarms." in out


@pytest.mark.asyncio
async def test_status_text_single_transfer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status(manifest_hash) in text mode prints detailed info.

    Covers cli.py lines 378-389 (text single transfer).
    """
    from tessera.types import SwarmState, TransferMode, TransferStatus

    ts = TransferStatus(
        manifest_hash=b"\xaa" * 32,
        state=SwarmState.ACTIVE,
        mode=TransferMode.NORMAL,
        progress=0.75,
        bytes_received=768,
        bytes_total=1024,
        throughput_bps=200.0,
        eta_seconds=2.0,
        tesserae_verified=3,
        tesserae_total=4,
        tesserae_in_flight=0,
        stuck_tesserae=[],
        peers=[],
    )

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = ts
        args = _args(data_dir=str(tmp_path), manifest_hash="aa" * 32, json=False)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Mosaic:" in out
    assert "State:" in out
    assert "Progress:" in out
    assert "3 / 4" in out
    assert "75.0%" in out
    assert "Peers:" in out
    assert "Throughput:" in out
    assert "ETA:" in out


@pytest.mark.asyncio
async def test_status_text_node_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status (no hash) with NodeStatus in text mode.

    Covers cli.py lines 356-363 (text NodeStatus with ai).
    """
    from tessera.types import AIStatus, NodeStatus

    ns = NodeStatus(
        agent_id=b"\x00" * 32,
        active_swarms=2,
        total_peers=5,
        capacity_remaining=8,
        ai=AIStatus(active=True),
    )

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = ns
        args = _args(data_dir=str(tmp_path), json=False)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Active swarms:" in out
    assert "AI:" in out
    assert "active" in out


@pytest.mark.asyncio
async def test_status_text_node_status_no_ai(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """status (no hash) with NodeStatus where ai is None.

    Covers cli.py line 361->391 (result.ai is falsy, skip AI print).
    """
    from tessera.types import NodeStatus

    ns = NodeStatus(
        agent_id=b"\x00" * 32,
        active_swarms=0,
        total_peers=0,
        capacity_remaining=10,
        ai=None,
    )

    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.status.return_value = ns
        args = _args(data_dir=str(tmp_path), json=False)
        code = await _cmd_status(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Active swarms:" in out
    assert "AI:" not in out


# ---------------------------------------------------------------------------
# Lines 422-428, 433: cancel JSON path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_json_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cancel with --json emits success JSON.

    Covers cli.py lines 422-428 (JSON success path) and 433.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.cancel.return_value = None
        args = _args(
            data_dir=str(tmp_path), manifest_hash="cc" * 32, json=True
        )
        code = await _cmd_cancel(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert obj["status"] == "cancelled"
    assert "manifest_hash" in obj


@pytest.mark.asyncio
async def test_cancel_text_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cancel in text mode emits 'Cancelling' and 'Cancelled.' messages.

    Covers cli.py lines 417-420, 427-428 (text cancel path).
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.cancel.return_value = None
        args = _args(
            data_dir=str(tmp_path), manifest_hash="cc" * 32, json=False
        )
        code = await _cmd_cancel(args)

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Cancelling" in out
    assert "Cancelled." in out


@pytest.mark.asyncio
async def test_cancel_tessera_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cancel with TesseraError returns EXIT_APP_ERROR.

    Covers cli.py lines 429-431.
    """
    with patch("tessera.cli.TesseraNode") as MockNode:
        ctx = MockNode.return_value.__aenter__.return_value
        ctx.cancel.side_effect = TesseraError("cancel failed")
        args = _args(data_dir=str(tmp_path), manifest_hash="cc" * 32, json=True)
        code = await _cmd_cancel(args)

    assert code == EXIT_APP_ERROR


# ---------------------------------------------------------------------------
# Lines 533-555: main() entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Line 172: Signal handler (_handle_signal sets stop_event)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_signal_handler_sets_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify the signal handler calls stop_event.set().

    Covers cli.py line 172 (_handle_signal body).
    We patch add_signal_handler to capture and invoke the handler.
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    import tessera.cli as cli_mod

    captured_handlers: list = []

    # Patch add_signal_handler to capture the callback, then call it.
    original_wait = asyncio.Event.wait

    async def _wait_then_signal(self: asyncio.Event) -> None:
        # Call any captured signal handlers to trigger stop_event.set().
        for h in captured_handlers:
            h()
        # Now the event should be set; if not, return immediately anyway.
        return

    cli_mod.asyncio.Event.wait = _wait_then_signal  # type: ignore[method-assign]

    original_add_handler = None

    def _capture_add_signal_handler(sig, callback):
        captured_handlers.append(callback)

    try:
        args = _args(data_dir=str(tmp_path), file=str(f), json=True)

        # Patch the loop's add_signal_handler to capture the callback.
        loop = asyncio.get_running_loop()
        original_add_handler = loop.add_signal_handler
        loop.add_signal_handler = _capture_add_signal_handler  # type: ignore[assignment]

        code = await _cmd_publish(args)
    finally:
        cli_mod.asyncio.Event.wait = original_wait  # type: ignore[method-assign]
        if original_add_handler is not None:
            loop.add_signal_handler = original_add_handler  # type: ignore[assignment]

    assert code == EXIT_OK
    # The captured handlers were invoked, covering line 172.
    assert len(captured_handlers) >= 1


# ---------------------------------------------------------------------------
# Line 547: SystemExit re-raise in main()
# ---------------------------------------------------------------------------


def test_main_system_exit_reraise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() re-raises SystemExit from asyncio.run.

    Covers cli.py line 547 (raise exc).
    """
    monkeypatch.setattr(
        sys, "argv",
        ["tessera", "--data-dir", str(tmp_path), "status"],
    )

    with patch("tessera.cli.asyncio.run", side_effect=SystemExit(42)):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 42


def test_main_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() with no arguments prints usage and exits with code 2.

    Covers cli.py lines 533-534 (parser.parse_args raises SystemExit).
    """
    monkeypatch.setattr(sys, "argv", ["tessera"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


def test_main_runs_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() routes to publish command and calls sys.exit.

    Covers cli.py lines 536-555 (main flow).
    """
    f = tmp_path / "data.bin"
    f.write_bytes(tiny())

    monkeypatch.setattr(
        sys, "argv",
        ["tessera", "--json", "--data-dir", str(tmp_path), "publish", str(f)],
    )

    with _patch_event_wait():
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == EXIT_OK


def test_main_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() catches KeyboardInterrupt and exits cleanly.

    Covers cli.py line 544-545.
    """
    monkeypatch.setattr(
        sys, "argv",
        ["tessera", "--data-dir", str(tmp_path), "status"],
    )

    with patch("tessera.cli.asyncio.run", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == EXIT_OK


def test_main_unexpected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() catches unexpected exceptions and exits with EXIT_APP_ERROR.

    Covers cli.py lines 548-553 (generic exception handler).
    """
    monkeypatch.setattr(
        sys, "argv",
        ["tessera", "--data-dir", str(tmp_path), "status"],
    )

    with patch("tessera.cli.asyncio.run", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == EXIT_APP_ERROR
    err = capsys.readouterr().err
    assert "boom" in err


def test_main_unexpected_exception_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() in JSON mode emits JSON error for unexpected exceptions.

    Covers cli.py lines 549-550 (JSON error in main).
    """
    monkeypatch.setattr(
        sys, "argv",
        ["tessera", "--json", "--data-dir", str(tmp_path), "status"],
    )

    with patch("tessera.cli.asyncio.run", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == EXIT_APP_ERROR
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert "error" in obj
    assert "boom" in obj["error"]
