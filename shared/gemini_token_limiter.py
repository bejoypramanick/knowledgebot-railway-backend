"""
Gemini API Token Rate Limiter using limits library with Redis backend.

Limits Gemini API calls to 100,000 input tokens per minute to stay well below
the 1,000,000 tokens/minute quota and avoid rate limit errors.

Uses Redis for distributed rate limiting across multiple instances.
"""

import time
from typing import Optional
import redis.asyncio as redis
from limits import RateLimitItemPerMinute
from limits.storage import RedisStorage
from limits.strategies import FixedWindowRateLimiter
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("gemini_token_limiter", "shared")

# Configuration
TARGET_TOKENS_PER_MINUTE = 100_000  # Conservative limit (10% of quota)
TOKENS_PER_SECOND = TARGET_TOKENS_PER_MINUTE / 60  # ~1,667 tokens/sec

# Rate limit key
RATE_LIMIT_KEY = "gemini:token_bucket"


class GeminiTokenLimiter:
    """Token bucket rate limiter for Gemini API using limits library."""

    def __init__(self):
        self._redis_client: Optional[redis.Redis] = None
        self._limiter: Optional[FixedWindowRateLimiter] = None
        self._storage: Optional[RedisStorage] = None

    async def _get_redis_client(self) -> redis.Redis:
        """Get or create Redis client for rate limiting."""
        if self._redis_client is None:
            from shared.redis_pubsub_manager import get_pubsub_redis

            self._redis_client = await get_pubsub_redis()
        return self._redis_client

    async def _get_limiter(self) -> FixedWindowRateLimiter:
        """Get or create the rate limiter instance."""
        if self._limiter is None:
            redis_client = await self._get_redis_client()
            # Create storage wrapper for async Redis client
            # limits library expects a sync Redis, so we use it directly
            self._storage = RedisStorage(
                f"redis://{self._redis_client.connection_pool.connection_kwargs.get('host', 'localhost')}:"
                f"{self._redis_client.connection_pool.connection_kwargs.get('port', 6379)}"
            )
            self._limiter = FixedWindowRateLimiter(storage=self._storage)
        return self._limiter

    async def wait_for_tokens(self, required_tokens: int) -> None:
        """
        Wait until enough tokens are available, then consume them.

        This implements a token bucket algorithm using the limits library:
        - Bucket refills at TOKENS_PER_SECOND rate
        - Max capacity is TARGET_TOKENS_PER_MINUTE
        - Blocks until required tokens are available

        Args:
            required_tokens: Number of tokens needed for the API call

        Raises:
            TimeoutError: If tokens could not be acquired within timeout
        """
        try:
            redis_client = await self._get_redis_client()
            max_retries = 60  # Max 60 seconds of waiting
            retry_count = 0

            while retry_count < max_retries:
                current_time = time.time()

                # Get current bucket state from Redis
                bucket_tokens_str = await redis_client.get("gemini:tokens")
                refill_time_str = await redis_client.get("gemini:refill_time")

                if bucket_tokens_str is None:
                    # Initialize bucket (full)
                    bucket_tokens = TARGET_TOKENS_PER_MINUTE
                    refill_time = current_time
                else:
                    bucket_tokens = float(bucket_tokens_str)
                    refill_time = float(refill_time_str) if refill_time_str else current_time

                # Calculate tokens to add based on time elapsed
                time_elapsed = current_time - refill_time
                tokens_to_add = time_elapsed * TOKENS_PER_SECOND

                # Update bucket (cap at max)
                bucket_tokens = min(TARGET_TOKENS_PER_MINUTE, bucket_tokens + tokens_to_add)
                refill_time = current_time

                # Check if we have enough tokens
                if bucket_tokens >= required_tokens:
                    # Consume tokens
                    bucket_tokens -= required_tokens
                    await redis_client.set("gemini:tokens", str(bucket_tokens), ex=3600)
                    await redis_client.set("gemini:refill_time", str(refill_time), ex=3600)

                    logger.info(
                        f"✅ Tokens approved: {required_tokens} tokens consumed "
                        f"(remaining: {bucket_tokens:.0f}/{TARGET_TOKENS_PER_MINUTE})"
                    )
                    return

                # Not enough tokens - calculate wait time
                tokens_needed = required_tokens - bucket_tokens
                wait_seconds = tokens_needed / TOKENS_PER_SECOND

                logger.warning(
                    f"⏳ Rate limit: Need {required_tokens} tokens, have {bucket_tokens:.0f}. "
                    f"Waiting {wait_seconds:.1f}s (attempt {retry_count + 1}/{max_retries})"
                )

                # Wait before retrying
                import asyncio

                await asyncio.sleep(min(wait_seconds, 1.0))  # Check every 1 second max
                retry_count += 1

            logger.error(
                f"❌ Token rate limit: Could not acquire {required_tokens} tokens after {max_retries}s"
            )
            raise TimeoutError(f"Could not acquire {required_tokens} tokens within timeout")

        except TimeoutError:
            raise
        except Exception as e:
            logger.error(f"❌ Error in token limiter: {e}")
            raise

    async def get_bucket_status(self) -> dict:
        """Get current token bucket status."""
        try:
            redis_client = await self._get_redis_client()

            bucket_tokens_str = await redis_client.get("gemini:tokens")
            refill_time_str = await redis_client.get("gemini:refill_time")

            if bucket_tokens_str is None:
                return {
                    "tokens_available": TARGET_TOKENS_PER_MINUTE,
                    "tokens_max": TARGET_TOKENS_PER_MINUTE,
                    "percent_available": 100,
                    "status": "initialized",
                }

            current_time = time.time()
            bucket_tokens = float(bucket_tokens_str)
            refill_time = float(refill_time_str) if refill_time_str else current_time

            # Calculate tokens to add based on time elapsed
            time_elapsed = current_time - refill_time
            tokens_to_add = time_elapsed * TOKENS_PER_SECOND
            bucket_tokens = min(TARGET_TOKENS_PER_MINUTE, bucket_tokens + tokens_to_add)

            return {
                "tokens_available": int(bucket_tokens),
                "tokens_max": TARGET_TOKENS_PER_MINUTE,
                "percent_available": (bucket_tokens / TARGET_TOKENS_PER_MINUTE) * 100,
                "refill_rate_per_second": TOKENS_PER_SECOND,
                "status": "active",
            }

        except Exception as e:
            logger.error(f"❌ Error getting bucket status: {e}")
            return {"status": "error", "error": str(e)}


# Global instance
_limiter: Optional[GeminiTokenLimiter] = None


def get_gemini_token_limiter() -> GeminiTokenLimiter:
    """Get or create the global Gemini token limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = GeminiTokenLimiter()
    return _limiter
