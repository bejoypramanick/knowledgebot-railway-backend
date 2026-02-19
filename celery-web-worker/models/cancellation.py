"""
Task Cancellation Handling

Provides a clean, centralized way to handle Celery task cancellation.
Instead of checking Redis flags everywhere, use a CancellationToken
that's passed through the call stack.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional
import logging
import redis

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("cancellation", "celery-web-worker")


class CancellationException(Exception):
    """Raised when a task is cancelled"""
    pass


@dataclass
class CancellationToken:
    """
    Cancellation token for tracking if a task should be cancelled.

    Pass this through the call stack instead of checking Redis everywhere.
    Reduces Redis calls and makes cancellation intent explicit.

    Example:
        token = CancellationToken.from_task_id(celery_task_id)
        if await token.is_cancelled():
            raise CancellationException("Task cancelled")
    """

    celery_task_id: str
    _cache_timestamp: float = 0.0
    _cache_value: bool = False
    _cache_ttl: float = 1.0  # Cache result for 1 second

    @staticmethod
    def from_task_id(celery_task_id: str) -> "CancellationToken":
        """Create token from task ID"""
        return CancellationToken(celery_task_id=celery_task_id)

    async def is_cancelled(self) -> bool:
        """
        Check if task is cancelled.
        Results are cached for 1 second to reduce Redis calls.
        """
        import time
        import os

        now = time.time()

        # Return cached value if fresh
        if now - self._cache_timestamp < self._cache_ttl:
            return self._cache_value

        # Check Redis
        try:
            redis_url = os.getenv('WEB_REDIS_URL', 'redis://localhost:6379/1')
            redis_conn = redis.from_url(redis_url, socket_connect_timeout=2)
            cancelled_key = f"task_cancelled:{self.celery_task_id}"
            result = redis_conn.exists(cancelled_key)
            redis_conn.close()

            # Update cache
            self._cache_timestamp = now
            self._cache_value = bool(result)
            return self._cache_value

        except redis.ConnectionError:
            logger.debug(f"ℹ️ Redis unavailable (OK in local dev)")
            return False
        except Exception as e:
            logger.debug(f"ℹ️ Cancellation check error: {e}")
            return False

    async def check_or_raise(self):
        """Check cancellation and raise if cancelled"""
        if await self.is_cancelled():
            logger.warning(f"❌ Task {self.celery_task_id} cancelled")
            raise CancellationException("Task cancelled")

    async def __aenter__(self):
        """Context manager support for cancellation checks"""
        await self.check_or_raise()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager"""
        pass


class CancellationCheckpoint:
    """
    Helper for strategically placing cancellation checks.

    Only check at boundaries (loop starts, before/after long operations),
    not everywhere in the code.

    Example:
        checkpoint = CancellationCheckpoint(token, name="BFS Loop")

        while queue:
            await checkpoint.check()  # Check once per loop iteration
            # process item
    """

    def __init__(self, token: CancellationToken, name: str = ""):
        self.token = token
        self.name = name
        self.check_count = 0

    async def check(self):
        """Check cancellation at this checkpoint"""
        self.check_count += 1
        if await self.token.is_cancelled():
            logger.warning(f"⏸️ Cancellation at checkpoint: {self.name}")
            raise CancellationException(f"Cancelled at {self.name}")

    def get_stats(self) -> dict:
        """Get checkpoint statistics"""
        return {
            "name": self.name,
            "checks": self.check_count
        }


# RECOMMENDED CANCELLATION CHECKPOINTS
# Only check at these strategic locations, not everywhere:
#
# 1. Loop starts (before iteration begins):
#    - BFS while loop (before popping URL)
#    - For-each page loop (before processing page)
#    - Document processing loop (before processing file)
#
# 2. Before long operations (before starting expensive work):
#    - Before uploading to Gemini
#    - Before downloading large files
#
# 3. After long operations (after blocking call completes):
#    - After Gemini upload completes (before recording)
#    - After file download completes (before processing)
#
# This gives responsiveness WITHOUT excessive Redis calls
