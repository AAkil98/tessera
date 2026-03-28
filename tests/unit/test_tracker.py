"""Unit tests for TrackerBackend — ts-spec-007 §5."""

from __future__ import annotations

import time

import pytest

from tessera.discovery.backend import PeerRecord
from tessera.discovery.tracker import TrackerBackend

_MH = b"\xaa" * 32
_AGENT = b"\xbb" * 32


# ---------------------------------------------------------------------------
# Mock HTTP helpers (protocol-based, no unittest.mock)
# ---------------------------------------------------------------------------


class _MockHTTPResponse:
    def __init__(self, data: object, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def json(self) -> object:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _MockHTTPClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.gets: list[dict] = []
        self._lookup_resp: list[dict] = []
        self._post_status: int = 200
        self._get_status: int = 200

    async def post(self, url: str, **kwargs: object) -> _MockHTTPResponse:
        self.posts.append({"url": url, **kwargs})
        return _MockHTTPResponse({"status": "ok"}, self._post_status)

    async def get(self, url: str, **kwargs: object) -> _MockHTTPResponse:
        self.gets.append({"url": url, **kwargs})
        return _MockHTTPResponse(self._lookup_resp, self._get_status)


class _MockHTTPClientWithAclose(_MockHTTPClient):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# announce
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_announce_posts_correct_payload() -> None:
    client = _MockHTTPClient()
    tb = TrackerBackend("https://tracker.test", client=client)

    await tb.announce(_MH, _AGENT, "seeder")

    assert len(client.posts) == 1
    call = client.posts[0]
    assert call["url"] == "https://tracker.test/announce"
    assert call["json"]["manifest_hash"] == _MH.hex()
    assert call["json"]["agent_id"] == _AGENT.hex()
    assert call["json"]["role"] == "seeder"


@pytest.mark.unit
async def test_announce_handles_http_error() -> None:
    client = _MockHTTPClient()
    client._post_status = 500
    tb = TrackerBackend("https://tracker.test", client=client)

    # Must not raise.
    await tb.announce(_MH, _AGENT, "seeder")


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_lookup_returns_peer_records() -> None:
    now = time.time()
    client = _MockHTTPClient()
    client._lookup_resp = [
        {"agent_id": _AGENT.hex(), "role": "seeder", "last_seen": now},
    ]
    tb = TrackerBackend("https://tracker.test", client=client)

    peers = await tb.lookup(_MH)

    assert len(peers) == 1
    assert isinstance(peers[0], PeerRecord)
    assert peers[0].agent_id == _AGENT
    assert peers[0].role == "seeder"
    assert peers[0].last_seen == pytest.approx(now)
    assert peers[0].source == "tracker"

    # Verify the GET was sent to the right URL with the right params.
    assert len(client.gets) == 1
    assert client.gets[0]["url"] == "https://tracker.test/lookup"
    assert client.gets[0]["params"]["hash"] == _MH.hex()


@pytest.mark.unit
async def test_lookup_empty_response() -> None:
    client = _MockHTTPClient()
    client._lookup_resp = []
    tb = TrackerBackend("https://tracker.test", client=client)

    peers = await tb.lookup(_MH)

    assert peers == []


@pytest.mark.unit
async def test_lookup_handles_http_error() -> None:
    client = _MockHTTPClient()
    client._get_status = 500
    tb = TrackerBackend("https://tracker.test", client=client)

    peers = await tb.lookup(_MH)

    assert peers == []


# ---------------------------------------------------------------------------
# unannounce
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_unannounce_posts_correct_payload() -> None:
    client = _MockHTTPClient()
    tb = TrackerBackend("https://tracker.test", client=client)

    await tb.unannounce(_MH, _AGENT)

    assert len(client.posts) == 1
    call = client.posts[0]
    assert call["url"] == "https://tracker.test/unannounce"
    assert call["json"]["manifest_hash"] == _MH.hex()
    assert call["json"]["agent_id"] == _AGENT.hex()


@pytest.mark.unit
async def test_unannounce_handles_error() -> None:
    client = _MockHTTPClient()
    client._post_status = 500
    tb = TrackerBackend("https://tracker.test", client=client)

    # Must not raise.
    await tb.unannounce(_MH, _AGENT)


# ---------------------------------------------------------------------------
# aclose
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_aclose_calls_client() -> None:
    client = _MockHTTPClientWithAclose()
    tb = TrackerBackend("https://tracker.test", client=client)

    await tb.aclose()

    assert client.closed is True


@pytest.mark.unit
async def test_aclose_no_method() -> None:
    client = _MockHTTPClient()
    # _MockHTTPClient has no aclose — must not crash.
    tb = TrackerBackend("https://tracker.test", client=client)

    await tb.aclose()
