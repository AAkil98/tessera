"""Unit tests for tessera.types.WatchHandle."""

from __future__ import annotations

import asyncio

import pytest

from tessera.types import WatchHandle


# ===================================================================
# WatchHandle
# ===================================================================


class TestWatchHandle:
    """WatchHandle wraps an asyncio.Task and provides cancel()."""

    @pytest.mark.unit
    async def test_cancel_stops_task(self) -> None:
        async def forever() -> None:
            while True:
                await asyncio.sleep(0.01)

        task = asyncio.create_task(forever())
        handle = WatchHandle(_task=task)
        await handle.cancel()
        assert task.done()
        assert task.cancelled()

    @pytest.mark.unit
    async def test_cancel_is_idempotent(self) -> None:
        """Calling cancel() twice does not raise."""
        async def forever() -> None:
            while True:
                await asyncio.sleep(0.01)

        task = asyncio.create_task(forever())
        handle = WatchHandle(_task=task)
        await handle.cancel()
        await handle.cancel()
        assert task.done()

    @pytest.mark.unit
    async def test_cancel_on_already_finished_task(self) -> None:
        """cancel() on a task that already returned normally."""
        async def immediate() -> None:
            return

        task = asyncio.create_task(immediate())
        await task  # Let it finish.
        handle = WatchHandle(_task=task)
        # Should not raise.
        await handle.cancel()
        assert task.done()

    @pytest.mark.unit
    async def test_task_attribute(self) -> None:
        async def noop() -> None:
            await asyncio.sleep(100)

        task = asyncio.create_task(noop())
        handle = WatchHandle(_task=task)
        assert handle._task is task
        await handle.cancel()

    @pytest.mark.unit
    async def test_cancel_on_task_that_raises(self) -> None:
        """cancel() works even if the task body would raise."""
        async def failing() -> None:
            await asyncio.sleep(100)
            raise RuntimeError("boom")

        task = asyncio.create_task(failing())
        handle = WatchHandle(_task=task)
        await handle.cancel()
        assert task.done()
        assert task.cancelled()
