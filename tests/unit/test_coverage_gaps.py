"""Unit tests targeting remaining coverage gaps across content, config, wire,
bridge, and transfer layers.

Every test is marked @pytest.mark.unit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tessera.content.bitfield import Bitfield
from tessera.content.chunker import Chunker
from tessera.content.manifest import (
    FORMAT_VERSION,
    MAGIC,
    ManifestBuilder,
    ManifestParser,
    _HEADER_FMT,
    _HEADER_SIZE,
    _encode_metadata,
)
from tessera.content.merkle import build_root
from tessera.config import TesseraConfig
from tessera.errors import ConfigError, MessageError
from tessera.wire import errors as werr
from tessera.wire.messages import (
    BitfieldMsg,
    Cancel,
    ExtensionMessage,
    Handshake,
    Have,
    KeepAlive,
    Piece,
    Request,
    decode,
    encode,
)
from tessera.wire.state_machine import PeerSession, PeerState
from tessera.bridge.bridge import IntelligenceBridge, PeerRankingHint
from tessera.bridge.ranking_adapter import RankingAdapter
from tessera.transfer.endgame import EndgameManager
from tessera.transfer.scheduler import RequestScheduler
from tessera.transfer.scorer import PeerScorer
from tessera.transfer.pipeline import RequestPipeline

# ===================================================================
# Helpers
# ===================================================================

_HASH = b"\xab" * 32


class _MockClient:
    """Returns a preset string from generate()."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append(prompt)
        return self._response


class _ManifestStoreMock:
    """Minimal stand-in for ManifestStore used by DiscoveryAdapter."""

    def __init__(self, index_data: list[tuple[bytes, dict[str, str]]]) -> None:
        self.index = self._Index(index_data)

    class _Index:
        def __init__(self, data: list[tuple[bytes, dict[str, str]]]) -> None:
            self._data = data

        def all_metadata(self) -> list[tuple[bytes, dict[str, str]]]:
            return list(self._data)


def _build_raw_manifest(
    *,
    tessera_count: int,
    tessera_size: int,
    file_size: int,
    last_tessera_size: int,
    root_hash: bytes = b"\x00" * 32,
    metadata_bytes: bytes = b"",
    leaf_hashes: bytes = b"",
    magic: bytes = MAGIC,
    version: int = FORMAT_VERSION,
) -> bytes:
    """Build raw manifest bytes with full control over every field."""
    header = struct.pack(
        _HEADER_FMT,
        magic,
        version,
        root_hash,
        tessera_count,
        tessera_size,
        file_size,
        last_tessera_size,
        len(metadata_bytes),
    )
    return header + metadata_bytes + leaf_hashes


def _valid_manifest_bytes(
    tessera_count: int = 4,
    tessera_size: int = 256,
    file_size: int = 1024,
) -> bytes:
    """Build a structurally valid manifest via ManifestBuilder."""
    builder = ManifestBuilder(
        file_size=file_size,
        tessera_size=tessera_size,
    )
    remaining = file_size
    for i in range(tessera_count):
        size = tessera_size if i < tessera_count - 1 else remaining
        data = bytes([i % 256]) * size
        leaf = hashlib.sha256(data).digest()
        builder.add_tessera(leaf)
        remaining -= size
    return builder.build()


# ===================================================================
# 1. content/bitfield.py — lines 26, 46, 114, 122
# ===================================================================


@pytest.mark.unit
def test_bitfield_negative_count():
    """Line 26: Bitfield(-1) raises ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        Bitfield(-1)


@pytest.mark.unit
def test_bitfield_from_base64_roundtrip():
    """Line 46/100: from_base64 classmethod round-trips via to_base64."""
    bf = Bitfield(16)
    bf.set(0)
    bf.set(5)
    bf.set(15)
    b64 = bf.to_base64()
    bf2 = Bitfield.from_base64(16, b64)
    assert bf == bf2
    assert bf2.get(0) is True
    assert bf2.get(5) is True
    assert bf2.get(15) is True
    assert bf2.get(1) is False


@pytest.mark.unit
def test_bitfield_repr():
    """Line 114: repr contains count and set count."""
    bf = Bitfield(8)
    r = repr(bf)
    assert "count=8" in r
    assert "set=0" in r


@pytest.mark.unit
def test_bitfield_count_property():
    """Line 46: .count property returns the total bit count."""
    bf = Bitfield(8)
    assert bf.count == 8
    bf2 = Bitfield(0)
    assert bf2.count == 0


@pytest.mark.unit
def test_bitfield_eq_non_bitfield():
    """Line 122: __eq__ returns NotImplemented for non-Bitfield operands."""
    bf = Bitfield(8)
    assert bf.__eq__("not a bitfield") is NotImplemented


# ===================================================================
# 2. content/chunker.py — lines 54, 105
# ===================================================================


@pytest.mark.unit
def test_chunker_tessera_count_zero_for_empty(tmp_path: Path):
    """Line 54 (FixedSizeChunking.tessera_count returns 0 for empty file)."""
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    chunker = Chunker(tessera_size=256, max_payload_size=1024)
    assert chunker.tessera_count(empty) == 0


@pytest.mark.unit
def test_chunker_last_tessera_size_zero_for_empty(tmp_path: Path):
    """Line 105 (Chunker.last_tessera_size returns 0 for empty file)."""
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    chunker = Chunker(tessera_size=256, max_payload_size=1024)
    assert chunker.last_tessera_size(empty) == 0


@pytest.mark.unit
def test_chunker_tessera_count_nonzero(tmp_path: Path):
    """Line 54: FixedSizeChunking.tessera_count returns correct count for non-empty file."""
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00" * 1000)
    chunker = Chunker(tessera_size=256, max_payload_size=1024)
    # ceil(1000 / 256) = 4
    assert chunker.tessera_count(f) == 4


# ===================================================================
# 3. content/manifest.py — lines 84, 172, 202, 216, 221, 228, 234
# ===================================================================


@pytest.mark.unit
def test_manifest_builder_invalid_leaf_hash_length():
    """Line 84: add_tessera with non-32-byte hash raises ValueError."""
    builder = ManifestBuilder(file_size=100, tessera_size=100)
    with pytest.raises(ValueError, match="32 bytes"):
        builder.add_tessera(b"\x00" * 16)


@pytest.mark.unit
def test_manifest_parser_truncated_header():
    """Line 172: manifest shorter than header raises ValueError."""
    with pytest.raises(ValueError, match="too short"):
        ManifestParser.parse(b"\x00" * 10)


@pytest.mark.unit
def test_manifest_parser_truncated_leaf_section():
    """Line 202: manifest truncated in the leaf hashes section."""
    # Build a header claiming 10 tesserae but provide no leaf data.
    leaf_hashes = b""  # should be 32*10 = 320 bytes
    raw = _build_raw_manifest(
        tessera_count=10,
        tessera_size=256,
        file_size=2560,
        last_tessera_size=256,
        leaf_hashes=leaf_hashes,
    )
    with pytest.raises(ValueError, match="truncated"):
        ManifestParser.parse(raw)


@pytest.mark.unit
def test_manifest_parser_zero_count_nonzero_size():
    """Line 216: tessera_count=0 but file_size != 0 raises ValueError."""
    raw = _build_raw_manifest(
        tessera_count=0,
        tessera_size=256,
        file_size=100,
        last_tessera_size=0,
        root_hash=build_root([]),
    )
    with pytest.raises(ValueError, match="tessera_count=0"):
        ManifestParser.parse(raw)


@pytest.mark.unit
def test_manifest_parser_single_tessera_size_mismatch():
    """Line 221: tessera_count=1, file_size != last_tessera_size."""
    leaf = hashlib.sha256(b"data").digest()
    raw = _build_raw_manifest(
        tessera_count=1,
        tessera_size=256,
        file_size=100,
        last_tessera_size=50,  # mismatch with file_size
        root_hash=build_root([leaf]),
        leaf_hashes=leaf,
    )
    with pytest.raises(ValueError, match="tessera_count=1"):
        ManifestParser.parse(raw)


@pytest.mark.unit
def test_manifest_parser_multi_tessera_geometry_mismatch():
    """Line 228: file_size inconsistent with tessera geometry."""
    leaf1 = hashlib.sha256(b"a" * 256).digest()
    leaf2 = hashlib.sha256(b"b" * 100).digest()
    raw = _build_raw_manifest(
        tessera_count=2,
        tessera_size=256,
        file_size=9999,  # should be 256 + 100 = 356
        last_tessera_size=100,
        root_hash=build_root([leaf1, leaf2]),
        leaf_hashes=leaf1 + leaf2,
    )
    with pytest.raises(ValueError, match="inconsistent"):
        ManifestParser.parse(raw)


@pytest.mark.unit
def test_manifest_parser_last_tessera_exceeds_tessera_size():
    """Line 234: last_tessera_size > tessera_size."""
    leaf1 = hashlib.sha256(b"a" * 256).digest()
    leaf2 = hashlib.sha256(b"b" * 256).digest()
    raw = _build_raw_manifest(
        tessera_count=2,
        tessera_size=256,
        file_size=256 + 512,  # geometry consistent with last_tessera_size=512
        last_tessera_size=512,  # > tessera_size
        root_hash=build_root([leaf1, leaf2]),
        leaf_hashes=leaf1 + leaf2,
    )
    with pytest.raises(ValueError, match="last_tessera_size"):
        ManifestParser.parse(raw)


# ===================================================================
# 4. config.py — lines 159, 161
# ===================================================================


@pytest.mark.unit
def test_config_negative_failure_weight():
    """Line 159: negative score_weight_failure raises ConfigError."""
    with pytest.raises(ConfigError, match="score_weight_failure"):
        TesseraConfig(
            score_weight_latency=0.5,
            score_weight_failure=-0.1,
            score_weight_throughput=0.6,
        )


@pytest.mark.unit
def test_config_negative_throughput_weight():
    """Line 161: negative score_weight_throughput raises ConfigError."""
    with pytest.raises(ConfigError, match="score_weight_throughput"):
        TesseraConfig(
            score_weight_latency=0.5,
            score_weight_failure=0.6,
            score_weight_throughput=-0.1,
        )


# ===================================================================
# 5. wire/messages.py — lines 196-198, 248, 254, 260
# ===================================================================


@pytest.mark.unit
def test_encode_extension_message():
    """Lines 196-198: encode(ExtensionMessage) returns msg_type + body."""
    msg = ExtensionMessage(msg_type=0x80, body=b"\xca\xfe\xba\xbe")
    wire = encode(msg)
    assert wire[0] == 0x80
    assert wire[1:] == b"\xca\xfe\xba\xbe"


@pytest.mark.unit
def test_decode_piece():
    """Lines 248-250: decode PIECE message."""
    payload = b"\x01\x02\x03\x04"
    wire = bytes([0x04]) + struct.pack("!I", 42) + payload
    msg = decode(wire)
    assert isinstance(msg, Piece)
    assert msg.index == 42
    assert msg.data == payload


@pytest.mark.unit
def test_decode_have():
    """Lines 254-255: decode HAVE message."""
    wire = bytes([0x05]) + struct.pack("!I", 77)
    msg = decode(wire)
    assert isinstance(msg, Have)
    assert msg.index == 77


@pytest.mark.unit
def test_decode_cancel():
    """Lines 260-261: decode CANCEL message."""
    wire = bytes([0x06]) + struct.pack("!I", 123)
    msg = decode(wire)
    assert isinstance(msg, Cancel)
    assert msg.index == 123


@pytest.mark.unit
def test_decode_piece_truncated():
    """Line 248: truncated PIECE raises MessageError."""
    wire = bytes([0x04, 0x00, 0x00])  # only 3 bytes
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_decode_have_truncated():
    """Line 254: truncated HAVE raises MessageError."""
    wire = bytes([0x05, 0x00])
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_decode_cancel_truncated():
    """Line 260: truncated CANCEL raises MessageError."""
    wire = bytes([0x06, 0x00, 0x00])
    with pytest.raises(MessageError) as exc_info:
        decode(wire)
    assert exc_info.value.error_code == werr.MALFORMED_MSG


@pytest.mark.unit
def test_encode_unknown_type_raises():
    """Line 198: encode with unknown type raises TypeError."""
    with pytest.raises(TypeError, match="cannot encode"):
        encode("not a message type")  # type: ignore[arg-type]


# ===================================================================
# 6. wire/state_machine.py — lines 80, 84, 174, branch 183
# ===================================================================


@pytest.mark.unit
def test_state_machine_state_property():
    """Line 80: .state returns current PeerState."""
    session = PeerSession()
    assert session.state == PeerState.AWAITING_HANDSHAKE


@pytest.mark.unit
def test_state_machine_set_peer_id():
    """Line 84: set_peer_id() stores and returns via .peer_id."""
    session = PeerSession()
    session.set_peer_id(b"\xaa\xbb")
    assert session.peer_id == b"\xaa\xbb"


@pytest.mark.unit
def test_state_machine_duplicate_bitfield_in_transfer():
    """Line 174: receiving a second BITFIELD in TRANSFER raises DUPLICATE_MSG."""
    session = PeerSession()
    session.on_receive(Handshake(1, _HASH, 4, 262_144))
    session.on_receive(BitfieldMsg(bitfield_bytes=b"\x00"))
    assert session.state == PeerState.TRANSFER
    with pytest.raises(MessageError) as exc_info:
        session.on_receive(BitfieldMsg(bitfield_bytes=b"\xff"))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_state_machine_send_transfer_before_bitfield():
    """Branch 183: sending a transfer message before bitfield raises."""
    session = PeerSession()
    session.on_send(Handshake(1, _HASH, 4, 262_144))
    # Handshake sent, but bitfield not yet sent.
    with pytest.raises(MessageError) as exc_info:
        session.on_send(Request(index=0))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_state_machine_send_on_closed():
    """Sending on a closed session raises UNEXPECTED_MSG."""
    session = PeerSession()
    session.close()
    with pytest.raises(MessageError) as exc_info:
        session.on_send(Handshake(1, _HASH, 4, 262_144))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_state_machine_send_duplicate_bitfield():
    """Line 174 (send-side): second BITFIELD raises DUPLICATE_MSG."""
    session = PeerSession()
    session.on_send(Handshake(1, _HASH, 4, 262_144))
    session.on_send(BitfieldMsg(bitfield_bytes=b"\x00"))
    with pytest.raises(MessageError) as exc_info:
        session.on_send(BitfieldMsg(bitfield_bytes=b"\xff"))
    assert exc_info.value.error_code == werr.DUPLICATE_MSG


@pytest.mark.unit
def test_state_machine_send_transfer_without_handshake():
    """Branch 183: send transfer message without having sent handshake."""
    session = PeerSession()
    # Neither handshake nor bitfield sent
    with pytest.raises(MessageError) as exc_info:
        session.on_send(Request(index=0))
    assert exc_info.value.error_code == werr.UNEXPECTED_MSG


@pytest.mark.unit
def test_state_machine_send_happy_path():
    """Branch 183->exit: send transfer message after valid handshake+bitfield.

    This tests the path where the guard at line 183 passes (both sent)
    and on_send falls through without raising.
    """
    session = PeerSession()
    session.on_send(Handshake(1, _HASH, 4, 262_144))
    session.on_send(BitfieldMsg(bitfield_bytes=b"\x00"))
    # This should succeed -- both handshake and bitfield sent
    session.on_send(Request(index=0))
    session.on_send(Have(index=1))
    session.on_send(Cancel(index=2))
    session.on_send(KeepAlive())


# ===================================================================
# 7. bridge/bridge.py — lines 71, 99, 129, 181, 206, 236
# ===================================================================


@pytest.mark.unit
async def test_bridge_generate_returns_none_when_inactive():
    """Line 71: _generate() returns None when bridge is inactive."""
    bridge = IntelligenceBridge(client=None)
    result = await bridge._generate("any prompt")
    assert result is None


@pytest.mark.unit
async def test_bridge_discover_returns_empty_when_inactive():
    """Line 99: discover() returns [] when inactive."""
    bridge = IntelligenceBridge(client=None)
    result = await bridge.discover("query", [])
    assert result == []


@pytest.mark.unit
async def test_bridge_discover_returns_empty_when_generate_fails():
    """Line 99: discover() returns [] when _generate returns None (via exception)."""

    class _FailClient:
        async def generate(self, prompt: str, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    bridge = IntelligenceBridge(client=_FailClient())
    index = [{"hash": "aa" * 32, "name": "f", "description": "", "mime": "", "size": 0}]
    result = await bridge.discover("query", index)
    assert result == []


@pytest.mark.unit
async def test_bridge_selection_returns_none_when_generate_fails():
    """Line 129: get_selection_hint returns None when generate returns None."""

    class _FailClient:
        async def generate(self, prompt: str, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    bridge = IntelligenceBridge(client=_FailClient())
    result = await bridge.get_selection_hint("f", "app/bin", 100, 4, 256)
    assert result is None


@pytest.mark.unit
async def test_bridge_discover_non_list_response():
    """Line 129 (discover): response is not a list returns []."""
    client = _MockClient(json.dumps({"not": "a list"}))
    bridge = IntelligenceBridge(client=client)
    index = [{"hash": "aa" * 32, "name": "f", "description": "", "mime": "", "size": 0}]
    result = await bridge.discover("query", index)
    assert result == []


@pytest.mark.unit
async def test_bridge_selection_hint_non_list_response():
    """Line 181: get_selection_hint returns None when response is not a list."""
    client = _MockClient(json.dumps({"not": "a list"}))
    bridge = IntelligenceBridge(client=client)
    result = await bridge.get_selection_hint("f", "app/bin", 100, 4, 256)
    assert result is None


@pytest.mark.unit
async def test_bridge_ranking_hint_returns_none_when_inactive():
    """Line 206: get_ranking_hint returns None when inactive."""
    bridge = IntelligenceBridge(client=None)
    result = await bridge.get_ranking_hint(0, [], "file", 0.0)
    assert result is None


@pytest.mark.unit
async def test_bridge_ranking_hint_non_dict_response():
    """Line 236: get_ranking_hint returns None when response is not a dict."""
    client = _MockClient(json.dumps([1, 2, 3]))
    bridge = IntelligenceBridge(client=client)
    peers = [{"id": "aabb", "score": 0.9, "latency_ms": 10,
              "failure_rate": 0.0, "bytes_delivered": 100}]
    result = await bridge.get_ranking_hint(0, peers, "file", 50.0)
    assert result is None


@pytest.mark.unit
async def test_bridge_ranking_hint_generate_returns_none():
    """Line 231: get_ranking_hint returns None when _generate returns None."""

    class _FailClient:
        async def generate(self, prompt: str, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    bridge = IntelligenceBridge(client=_FailClient())
    peers = [{"id": "aabb", "score": 0.9, "latency_ms": 10,
              "failure_rate": 0.0, "bytes_delivered": 100}]
    result = await bridge.get_ranking_hint(0, peers, "file", 50.0)
    assert result is None


@pytest.mark.unit
async def test_bridge_ranking_hint_parse_exception():
    """Lines 247-249: get_ranking_hint parse exception returns None."""
    # Return JSON that will cause bytes.fromhex to fail
    client = _MockClient(json.dumps({
        "ranked_peers": ["not_valid_hex"],
        "confidence": 0.9,
    }))
    bridge = IntelligenceBridge(client=client)
    peers = [{"id": "not_valid_hex", "score": 0.9, "latency_ms": 10,
              "failure_rate": 0.0, "bytes_delivered": 100}]
    result = await bridge.get_ranking_hint(0, peers, "file", 50.0)
    # bytes.fromhex("not_valid_hex") will raise, triggering exception path
    assert result is None


@pytest.mark.unit
async def test_bridge_moderate_metadata_inactive():
    """Line 263: moderate_metadata returns (True, '', 1.0) when inactive."""
    bridge = IntelligenceBridge(client=None)
    allowed, reason, confidence = await bridge.moderate_metadata({"name": "file"})
    assert allowed is True
    assert reason == ""
    assert confidence == 1.0


@pytest.mark.unit
async def test_bridge_moderate_metadata_parse_exception():
    """Lines 289-291: moderate_metadata parse failure returns safe default."""
    # Return non-JSON response that will trigger parse failure
    client = _MockClient("not valid json {{{")
    bridge = IntelligenceBridge(client=client)
    allowed, reason, confidence = await bridge.moderate_metadata({"name": "file"})
    assert allowed is True
    assert reason == ""
    assert confidence == 1.0


# ===================================================================
# 8. bridge/discovery_adapter.py — lines 56-57
# ===================================================================


@pytest.mark.unit
async def test_discovery_adapter_inactive_bridge():
    """Line 33: DiscoveryAdapter.query returns [] when bridge is inactive."""
    from tessera.bridge.discovery_adapter import DiscoveryAdapter

    bridge = IntelligenceBridge(client=None)
    store = _ManifestStoreMock([(b"\xaa" * 32, {"name": "test"})])
    adapter = DiscoveryAdapter(bridge, store)
    results = await adapter.query("anything")
    assert results == []


@pytest.mark.unit
async def test_discovery_adapter_empty_index():
    """Line 37: DiscoveryAdapter.query returns [] when manifest index is empty."""
    from tessera.bridge.discovery_adapter import DiscoveryAdapter

    client = _MockClient("[]")
    bridge = IntelligenceBridge(client=client)
    store = _ManifestStoreMock([])  # empty index
    adapter = DiscoveryAdapter(bridge, store)
    results = await adapter.query("anything")
    assert results == []


@pytest.mark.unit
async def test_discovery_adapter_valid_result_parsing():
    """Lines 44-48: DiscoveryAdapter.query parses valid results into DiscoveryResult."""
    from tessera.bridge.discovery_adapter import DiscoveryAdapter
    from tessera.types import DiscoveryResult

    known_hash_hex = "aa" * 32
    client = _MockClient("[]")  # won't be used directly
    bridge = IntelligenceBridge(client=client)
    store = _ManifestStoreMock([
        (bytes.fromhex(known_hash_hex), {"name": "test_file"}),
    ])
    adapter = DiscoveryAdapter(bridge, store)

    # Mock discover to return a valid result
    async def _mock_discover(query, index, max_results=10):
        return [
            {"manifest_hash": known_hash_hex, "relevance_score": 0.85, "reason": "good match"},
        ]

    bridge.discover = _mock_discover
    results = await adapter.query("test")
    assert len(results) == 1
    assert isinstance(results[0], DiscoveryResult)
    assert results[0].manifest_hash == bytes.fromhex(known_hash_hex)
    assert results[0].name == "test_file"
    assert results[0].relevance_score == pytest.approx(0.85)


@pytest.mark.unit
async def test_discovery_adapter_bad_hex_in_manifest_hash():
    """Lines 56-57: bad hex in manifest_hash triggers continue (exception path)."""
    from tessera.bridge.discovery_adapter import DiscoveryAdapter

    client = _MockClient("[]")
    bridge = IntelligenceBridge(client=client)
    store = _ManifestStoreMock([
        (b"\xaa" * 32, {"name": "test_file"}),
    ])
    adapter = DiscoveryAdapter(bridge, store)

    # Mock discover to return a result with bad hex that will cause
    # bytes.fromhex to raise, triggering the except/continue path.
    async def _mock_discover(query, index, max_results=10):
        return [
            {"manifest_hash": "not_valid_hex", "relevance_score": 0.9, "reason": "x"},
        ]

    bridge.discover = _mock_discover
    results = await adapter.query("test")
    assert results == []


# ===================================================================
# 9. bridge/ranking_adapter.py — branch 74->73
# ===================================================================


@pytest.mark.unit
async def test_ranking_adapter_inactive_get_hint():
    """Line 40: get_hint returns None when bridge is inactive."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge)
    peers = [{"id": "aabb", "score": 0.9, "latency_ms": 10,
              "failure_rate": 0.0, "bytes_delivered": 100}]
    result = await adapter.get_hint(0, peers, "file", 50.0)
    assert result is None


@pytest.mark.unit
def test_ranking_apply_hint_peer_not_in_score_ranked():
    """Branch 74->73: apply() with hint containing peer not in score_ranked
    (low confidence path, peer not in result list is simply skipped)."""
    bridge = IntelligenceBridge(client=None)
    adapter = RankingAdapter(bridge, confidence_threshold=0.7)

    score_ranked = [b"\xaa", b"\xbb"]
    hint = PeerRankingHint(
        tessera_index=0,
        ranked_peers=[b"\xff"],  # not in score_ranked at all
        confidence=0.5,  # low confidence path
    )

    result = adapter.apply(score_ranked, hint)
    # \xff is not in score_ranked, so it's simply not found in result
    # and the loop skips it. Original order preserved.
    assert result == [b"\xaa", b"\xbb"]


# ===================================================================
# 10. transfer/endgame.py — line 64
# ===================================================================


@pytest.mark.unit
def test_endgame_swarm_limit_zero_peers():
    """Line 64: endgame_swarm_limit with 0 connected peers clamps to max(0,1)=1."""
    em = EndgameManager(endgame_threshold=20, max_endgame_requests=100)
    # remaining=5, connected_peers=0 -> min(5 * max(0, 1), 100) = min(5, 100) = 5
    result = em.endgame_swarm_limit(remaining=5, connected_peers=0)
    assert result == 5


@pytest.mark.unit
def test_endgame_swarm_limit_capped():
    """endgame_swarm_limit respects max_endgame_requests cap."""
    em = EndgameManager(endgame_threshold=20, max_endgame_requests=10)
    # remaining=20, connected_peers=5 -> min(20*5, 10) = 10
    result = em.endgame_swarm_limit(remaining=20, connected_peers=5)
    assert result == 10


# ===================================================================
# 11. transfer/scheduler.py — lines 155, 169, 184, 188, 202
# ===================================================================


def _peer(n: int) -> bytes:
    return bytes([n]) * 8


@pytest.mark.unit
def test_scheduler_remove_peer():
    """Line 155: remove_peer drops a peer's bitfield from tracking."""
    sched = RequestScheduler(tessera_count=10)
    sched.update_peer_bitfield(_peer(1), {0, 1, 2})
    sched.remove_peer(_peer(1))
    # After removal the peer's pieces are gone from peer_bitfields
    assert _peer(1) not in sched._peer_bitfields


@pytest.mark.unit
def test_scheduler_remove_peer_nonexistent():
    """Line 155: remove_peer on unknown peer is a no-op."""
    sched = RequestScheduler(tessera_count=10)
    sched.remove_peer(_peer(99))  # should not raise


@pytest.mark.unit
def test_scheduler_mark_failed():
    """Line 169: mark_failed removes index from in-flight set."""
    sched = RequestScheduler(tessera_count=10)
    sched.mark_in_flight(5)
    assert 5 in sched._in_flight
    sched.mark_failed(5)
    assert 5 not in sched._in_flight


@pytest.mark.unit
def test_scheduler_remaining_property():
    """Line 184: remaining returns count of un-held tesserae."""
    bf = Bitfield(10)
    bf.set(0)
    bf.set(1)
    bf.set(2)
    sched = RequestScheduler(tessera_count=10, local_bitfield=bf)
    assert sched.remaining == 7


@pytest.mark.unit
def test_scheduler_in_flight_count_property():
    """Line 188: in_flight_count returns current in-flight set size."""
    sched = RequestScheduler(tessera_count=10)
    assert sched.in_flight_count == 0
    sched.mark_in_flight(0)
    sched.mark_in_flight(1)
    assert sched.in_flight_count == 2


@pytest.mark.unit
def test_scheduler_select_zero_peers():
    """Line 202/209: select with 0 peers falls into sequential path."""
    sched = RequestScheduler(tessera_count=5)
    # No peers registered, so n_peers=0, falls into sequential
    result = sched.select(3)
    assert result == [0, 1, 2]


@pytest.mark.unit
def test_scheduler_select_one_peer():
    """Line 209: select with 1 peer uses sequential selection."""
    import random

    sched = RequestScheduler(tessera_count=5, rng=random.Random(42))
    sched.update_peer_bitfield(_peer(1), {0, 1, 2, 3, 4})
    sched._requests_issued = 10  # past random bootstrap
    result = sched.select(3)
    assert result == [0, 1, 2]


@pytest.mark.unit
def test_scheduler_select_all_held():
    """select returns [] when all tesserae are held."""
    bf = Bitfield(4)
    for i in range(4):
        bf.set(i)
    sched = RequestScheduler(tessera_count=4, local_bitfield=bf)
    assert sched.select(5) == []


# ===================================================================
# 12. transfer/scorer.py — lines 228, 236, branch 102
# ===================================================================


@pytest.mark.unit
def test_scorer_is_deprioritized():
    """Line 228: is_deprioritized returns True for low-scoring peers."""
    scorer = PeerScorer()
    scorer.add_peer(b"\xaa")
    # Drive score way down with mismatches
    for _ in range(5):
        scorer.on_hash_mismatch(b"\xaa")
    assert scorer.is_deprioritized(b"\xaa") is True


@pytest.mark.unit
def test_scorer_all_scores():
    """Line 236: all_scores returns dict of all registered peers and scores."""
    scorer = PeerScorer()
    scorer.add_peer(b"\xaa")
    scorer.add_peer(b"\xbb")
    scores = scorer.all_scores()
    assert b"\xaa" in scores
    assert b"\xbb" in scores
    assert len(scores) == 2
    assert all(isinstance(v, float) for v in scores.values())


@pytest.mark.unit
def test_scorer_score_unknown_peer():
    """Branch 102: score() for unknown peer raises KeyError."""
    scorer = PeerScorer()
    with pytest.raises(KeyError):
        scorer.score(b"\xff")


@pytest.mark.unit
def test_scorer_has_peer():
    """has_peer returns correct boolean."""
    scorer = PeerScorer()
    assert scorer.has_peer(b"\xaa") is False
    scorer.add_peer(b"\xaa")
    assert scorer.has_peer(b"\xaa") is True


@pytest.mark.unit
def test_scorer_remove_peer():
    """remove_peer deregisters the peer."""
    scorer = PeerScorer()
    scorer.add_peer(b"\xaa")
    scorer.remove_peer(b"\xaa")
    assert scorer.has_peer(b"\xaa") is False


@pytest.mark.unit
def test_scorer_should_displace():
    """should_displace returns True for low-scoring peers."""
    scorer = PeerScorer()
    scorer.add_peer(b"\xaa")
    for _ in range(3):
        scorer.on_hash_mismatch(b"\xaa")
    assert scorer.should_displace(b"\xaa") is True


@pytest.mark.unit
def test_scorer_update_failure_rate_empty_window():
    """Branch 102->exit: update_failure_rate with empty window is a no-op."""
    from tessera.transfer.scorer import _PeerState, PeerMetrics

    state = _PeerState(score=0.5)
    # Window is empty by default
    assert len(state._window) == 0
    state.update_failure_rate()
    # failure_rate should remain 0.0 (unchanged)
    assert state.metrics.failure_rate == 0.0


# ===================================================================
# 13. transfer/pipeline.py — branch 118->exit
# ===================================================================


@pytest.mark.unit
async def test_pipeline_acquire_base_exception_releases_swarm_sem():
    """BaseException during peer_sem.acquire() releases the swarm sem."""
    pipe = RequestPipeline(max_per_peer=5, max_per_swarm=20)
    peer = b"\x01" * 8

    # Block the peer semaphore so cancellation hits during peer_sem.acquire().
    pipe._peer_sems[peer] = asyncio.Semaphore(0)

    async def try_acquire():
        await pipe.acquire(peer, index=99)

    task = asyncio.create_task(try_acquire())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Verify swarm semaphore was released (no leak).
    acquired = 0
    for i in range(20):
        if pipe._swarm_sem._value > 0:
            await pipe._swarm_sem.acquire()
            acquired += 1
        else:
            break
    assert acquired == 20


@pytest.mark.unit
async def test_pipeline_release_with_removed_peer_sem():
    """Branch 118->exit: release when peer_id has no semaphore entry.

    This covers the False branch of `if sem is not None:` at line 118.
    """
    pipe = RequestPipeline(max_per_peer=5, max_per_swarm=20)
    peer = b"\x01" * 8

    record = await pipe.acquire(peer, index=0)
    assert pipe.in_flight_count() == 1

    # Remove the peer's semaphore entry before releasing.
    del pipe._peer_sems[peer]

    # release should still work without error; it just skips the peer sem.
    pipe.release(record)
    assert pipe.in_flight_count() == 0
