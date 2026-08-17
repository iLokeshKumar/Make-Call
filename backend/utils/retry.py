"""
Agent retry and circuit-breaker utilities.

Usage
-----
# Retry a flaky async operation up to 3 times with exponential back-off:
from utils.retry import retry_async

@retry_async(max_attempts=3, base_delay=0.5, exceptions=(httpx.TimeoutException,))
async def call_apollo_api(...):
    ...

# Wrap an agent run() call with full retry + fallback:
from utils.retry import with_fallback

result = await with_fallback(
    primary=lambda: my_agent.run(query, company_id),
    fallback=lambda: {"output": "Agent temporarily unavailable.", "errors": []},
    max_attempts=2,
)
"""
from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Awaitable, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)

# Retry decorator

def retry_async(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log_attempts: bool = True,
):
    """
    Decorator: retry an async function up to *max_attempts* times with
    exponential back-off on specified exception types.

    Args:
        max_attempts: Maximum number of total attempts (1 = no retry).
        base_delay: Seconds to wait before the second attempt.
        backoff: Multiplier applied to delay on each failure (2.0 = double).
        exceptions: Exception types that trigger a retry. Others propagate immediately.
        log_attempts: Log a WARNING on each failed attempt.
    """
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    if log_attempts:
                        logger.warning(
                            "[retry] %s attempt %d/%d failed: %s — retrying in %.1fs",
                            fn.__qualname__, attempt, max_attempts, exc, delay,
                        )
                    await asyncio.sleep(delay)
                    delay *= backoff
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


# Circuit breaker

class CircuitBreaker:
    """
    Simple per-agent circuit breaker.

    States:
      CLOSED  — normal; requests pass through.
      OPEN    — agent is failing; requests are blocked immediately.
      HALF    — cooldown elapsed; one probe request is allowed.

    Args:
        name: Agent name shown in log messages.
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout: Seconds before transitioning OPEN → HALF.
    """

    CLOSED = "closed"
    OPEN   = "open"
    HALF   = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.monotonic() - self._opened_at >= self._recovery:
                self._state = self.HALF
                logger.info("[CircuitBreaker:%s] → HALF_OPEN (probe allowed)", self.name)
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        if self._state != self.CLOSED:
            logger.info("[CircuitBreaker:%s] → CLOSED", self.name)
        self._state = self.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._state == self.CLOSED:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            logger.error(
                "[CircuitBreaker:%s] → OPEN after %d failures", self.name, self._failures
            )

    def is_open(self) -> bool:
        return self.state == self.OPEN

    def allow_request(self) -> bool:
        s = self.state
        return s in (self.CLOSED, self.HALF)


# Global registry — one breaker per agent name
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = asyncio.Lock()


def get_breaker(name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> CircuitBreaker:
    """Return (or create) the circuit breaker for an agent."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
    return _breakers[name]



async def with_fallback(
    primary: Callable[[], Awaitable[Any]],
    fallback: Callable[[], Any],
    agent_name: str = "agent",
    max_attempts: int = 2,
    base_delay: float = 0.5,
) -> Any:
    """
    Run *primary* with retry and circuit-breaker protection.
    If all attempts fail (or the circuit is open), return *fallback()*.

    Args:
        primary: Async callable to attempt (no args — use lambda).
        fallback: Sync or async callable returning the degraded result.
        agent_name: Key for the circuit breaker registry.
        max_attempts: Max retry attempts before giving up.
        base_delay: Initial back-off delay in seconds.
    """
    breaker = get_breaker(agent_name)

    if not breaker.allow_request():
        logger.warning("[%s] Circuit open — returning fallback", agent_name)
        result = fallback()
        return await result if asyncio.iscoroutine(result) else result

    delay = base_delay
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await primary()
            breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            breaker.record_failure()
            if attempt < max_attempts:
                logger.warning(
                    "[%s] attempt %d/%d failed: %s — retrying in %.1fs",
                    agent_name, attempt, max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2.0
            else:
                logger.error("[%s] all %d attempts failed: %s", agent_name, max_attempts, exc, exc_info=True)

    fb = fallback()
    return await fb if asyncio.iscoroutine(fb) else fb
