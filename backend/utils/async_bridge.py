"""
Async/Sync Bridge Utilities

Proper async boundary management for mixed sync/async codebases.
Handles calling async functions from sync contexts and vice versa.
"""
import asyncio
import contextvars
import functools
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Shared thread pool for sync-to-async bridges to avoid creating new pools
_BRIDGE_EXECUTOR: ThreadPoolExecutor | None = None
_BRIDGE_EXECUTOR_MAX_WORKERS = 4


def _get_bridge_executor() -> ThreadPoolExecutor:
    """Get or create the shared thread pool for async bridges."""
    global _BRIDGE_EXECUTOR
    if _BRIDGE_EXECUTOR is None:
        _BRIDGE_EXECUTOR = ThreadPoolExecutor(
            max_workers=_BRIDGE_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="async_bridge"
        )
    return _BRIDGE_EXECUTOR


def is_async_context() -> bool:
    """Check if currently running in an async context (event loop running)."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def run_async_from_sync(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine from a sync context.
    
    Handles two scenarios:
    1. No event loop running: Use asyncio.run() directly
    2. Event loop already running: Offload to thread pool with new loop
    
    ContextVars are preserved across thread boundaries for logging/tracing.
    
    Args:
        coro: The coroutine to execute
        
    Returns:
        The result of the coroutine
        
    Example:
        result = run_async_from_sync(some_async_function(arg1, arg2))
    """
    try:
        loop = asyncio.get_running_loop()
        # Event loop is running - must use thread pool
        ctx = contextvars.copy_context()
        executor = _get_bridge_executor()
        future = executor.submit(ctx.run, asyncio.run, coro)
        return future.result()
    except RuntimeError:
        # No event loop - safe to use asyncio.run()
        return asyncio.run(coro)


async def run_sync_in_executor(func: callable, *args, **kwargs) -> Any:
    """
    Run a sync function in a thread pool from async context.
    
    Use this when you need to call blocking I/O or CPU-intensive sync code
    from an async function without blocking the event loop.
    
    Args:
        func: The sync function to execute
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
        
    Returns:
        The result of the function
        
    Example:
        result = await run_sync_in_executor(blocking_db_query, query_param)
    """
    loop = asyncio.get_running_loop()
    executor = _get_bridge_executor()
    partial_func = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(executor, partial_func)


def async_to_sync(async_func: callable) -> callable:
    """
    Decorator to make an async function callable from sync context.
    
    The wrapped function will automatically detect the context and either:
    - Call the async function directly if in async context
    - Use run_async_from_sync if in sync context
    
    Example:
        @async_to_sync
        async def my_async_function(arg):
            await asyncio.sleep(1)
            return arg * 2
            
        # Can now call from sync code:
        result = my_async_function(5)  # Returns 10
    """
    @functools.wraps(async_func)
    def wrapper(*args, **kwargs):
        coro = async_func(*args, **kwargs)
        if is_async_context():
            # Already in async context - return coroutine to be awaited
            return coro
        else:
            # Sync context - run it
            return run_async_from_sync(coro)
    return wrapper


def sync_to_async(sync_func: callable) -> callable:
    """
    Decorator to make a sync function safely callable from async context.
    
    The wrapped function will run in a thread pool to avoid blocking the event loop.
    
    Example:
        @sync_to_async
        def blocking_operation(data):
            time.sleep(5)  # Blocking I/O
            return process(data)
            
        # Can now await from async code:
        result = await blocking_operation(my_data)
    """
    @functools.wraps(sync_func)
    async def wrapper(*args, **kwargs):
        return await run_sync_in_executor(sync_func, *args, **kwargs)
    return wrapper


def cleanup_bridge_executor():
    """
    Shutdown the shared thread pool executor.
    
    Call this during application shutdown to ensure clean termination.
    """
    global _BRIDGE_EXECUTOR
    if _BRIDGE_EXECUTOR is not None:
        _BRIDGE_EXECUTOR.shutdown(wait=True)
        _BRIDGE_EXECUTOR = None
        logger.info("Async bridge executor shutdown complete")
