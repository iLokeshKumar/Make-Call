"""Tests for async/sync bridge utilities."""
import asyncio
import time
import pytest

from utils.async_bridge import (
    is_async_context,
    run_async_from_sync,
    run_sync_in_executor,
    async_to_sync,
    sync_to_async,
)


def test_is_async_context_returns_false_in_sync():
    """is_async_context should return False when called from sync code."""
    assert is_async_context() is False


@pytest.mark.asyncio
async def test_is_async_context_returns_true_in_async():
    """is_async_context should return True when called from async code."""
    assert is_async_context() is True


def test_run_async_from_sync_no_loop():
    """run_async_from_sync should work when no event loop is running."""
    async def sample_coro():
        await asyncio.sleep(0.01)
        return "result"
    
    result = run_async_from_sync(sample_coro())
    assert result == "result"


@pytest.mark.asyncio
async def test_run_async_from_sync_with_running_loop():
    """run_async_from_sync should use thread pool when loop is running."""
    async def sample_coro():
        await asyncio.sleep(0.01)
        return "from_thread"
    
    # Call from within async context - should offload to thread
    result = run_async_from_sync(sample_coro())
    assert result == "from_thread"


@pytest.mark.asyncio
async def test_run_sync_in_executor():
    """run_sync_in_executor should run blocking code without blocking loop."""
    def blocking_func(x):
        time.sleep(0.01)  # Simulate blocking I/O
        return x * 2
    
    result = await run_sync_in_executor(blocking_func, 5)
    assert result == 10


def test_async_to_sync_decorator_from_sync():
    """@async_to_sync should make async function callable from sync code."""
    @async_to_sync
    async def async_func(x):
        await asyncio.sleep(0.01)
        return x + 1
    
    # Call from sync context
    result = async_func(5)
    assert result == 6


@pytest.mark.asyncio
async def test_async_to_sync_decorator_from_async():
    """@async_to_sync should return coroutine when called from async context."""
    @async_to_sync
    async def async_func(x):
        await asyncio.sleep(0.01)
        return x + 1
    
    # Call from async context - should return coroutine
    coro = async_func(5)
    assert asyncio.iscoroutine(coro)
    result = await coro
    assert result == 6


@pytest.mark.asyncio
async def test_sync_to_async_decorator():
    """@sync_to_async should make sync function awaitable."""
    @sync_to_async
    def sync_func(x):
        time.sleep(0.01)
        return x * 3
    
    result = await sync_func(4)
    assert result == 12


def test_run_async_from_sync_preserves_return_value():
    """run_async_from_sync should preserve complex return values."""
    async def complex_return():
        await asyncio.sleep(0.01)
        return {"status": "ok", "data": [1, 2, 3]}
    
    result = run_async_from_sync(complex_return())
    assert result == {"status": "ok", "data": [1, 2, 3]}


def test_run_async_from_sync_propagates_exceptions():
    """run_async_from_sync should propagate exceptions from async code."""
    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("test error")
    
    with pytest.raises(ValueError, match="test error"):
        run_async_from_sync(failing_coro())
