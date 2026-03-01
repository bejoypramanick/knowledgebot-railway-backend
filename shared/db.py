"""Unified database utilities for PostgreSQL connections across all services."""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, Any

import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential
from shared.correlation_id import get_correlation_id
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("db", "database")

class DatabaseManager:
    """Robust database connection pool manager with health checks and auto-recovery."""
    
    _instance: Optional['DatabaseManager'] = None
    _lock = asyncio.Lock()

    def __init__(self, connection_url: Optional[str] = None):
        self._pool: Optional[asyncpg.Pool] = None
        self._connection_url = connection_url or os.getenv("DATABASE_URL")
        
        # Configure SSL for Railway PostgreSQL
        # Use prefer: allow connection with SSL, but don't fail if unavailable
        # This is more resilient than require for internal connections
        if self._connection_url:
            if 'sslmode=' not in self._connection_url:
                # Add sslmode=prefer for more resilient connections
                self._connection_url += '&sslmode=prefer' if '?' in self._connection_url else '?sslmode=prefer'
                logger.info(f"📊 Added sslmode=prefer to DATABASE_URL for Railway compatibility")
            else:
                logger.info(f"📊 DATABASE_URL already has sslmode configured")
        
        # Get pool size from environment variables with sensible defaults
        # DB_POOL_MIN_SIZE: Minimum connections per worker (default: 10)
        # DB_POOL_MAX_SIZE: Maximum connections per worker (default: 20)
        # Note: Configuration service can make 6+ parallel queries, so we need headroom
        min_size_env = os.getenv('DB_POOL_MIN_SIZE')
        max_size_env = os.getenv('DB_POOL_MAX_SIZE')

        # Use environment variables if set, otherwise use defaults
        # Note: If env vars are set to very small values (1, 2, 3), they're likely wrong
        # Use sensible minimums to prevent connection pool exhaustion
        min_size_raw = int(min_size_env) if min_size_env else 10
        max_size_raw = int(max_size_env) if max_size_env else 20

        # Enforce sensible minimums - never go below these
        min_size = max(min_size_raw, 10)  # At least 10 minimum connections
        max_size = max(max_size_raw, 20)  # At least 20 maximum connections

        # Warn if environment variables were too small
        if min_size_env and int(min_size_env) < 10:
            logger.warning(f"⚠️ [DB_POOL] DB_POOL_MIN_SIZE set to {min_size_env} but enforcing minimum of 10")
        if max_size_env and int(max_size_env) < 20:
            logger.warning(f"⚠️ [DB_POOL] DB_POOL_MAX_SIZE set to {max_size_env} but enforcing minimum of 20")

        logger.info(f"📊 [DB_POOL_ENV] DB_POOL_MIN_SIZE={min_size_env} (using: {min_size}), DB_POOL_MAX_SIZE={max_size_env} (using: {max_size})")

        # Log database connection info for debugging
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            # Mask the password in logs
            masked_url = db_url.split('@')[0] + '@' + db_url.split('@')[1] if '@' in db_url else db_url
            logger.info(f"📊 [DATABASE_URL] {masked_url}")
        else:
            logger.warning("⚠️ [DATABASE_URL] Not set!")
        
        # Optimized pool sizing for handling concurrent requests
        # With asyncio, we need enough connections to handle multiple concurrent operations
        # Configuration service makes up to 6 parallel queries per request
        # Setting max_size=20 allows handling multiple concurrent requests per worker
        # This prevents connection exhaustion errors when requests overlap
        self._pool_config = {
            'min_size': min_size,
            'max_size': max_size,
            'command_timeout': 30.0,  # Increased from 15s for slow database
            'max_inactive_connection_lifetime': 30.0,  # Close idle connections faster (was 60s)
            'max_queries': 50000,  # Increased from 10000
            'server_settings': {
                'timezone': 'UTC',
                'application_name': 'knowledgebot_backend_shared',
                'tcp_keepalives_idle': '10',  # More aggressive keepalive (was 30s)
                'tcp_keepalives_interval': '5',  # (was 10s)
                'tcp_keepalives_count': '5',  # (was 3)
                'statement_timeout': '15000'
            }
        }
        self._last_health_check = 0
        self._health_check_interval = 30  # seconds
        
        logger.info(f"📊 [DB_POOL_CONFIG] Pool size: min={min_size}, max={max_size}")

    @classmethod
    async def get_instance(cls) -> 'DatabaseManager':
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = DatabaseManager()
        return cls._instance

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=lambda e: isinstance(e, (
            ConnectionRefusedError, 
            OSError, 
            asyncpg.exceptions.ConnectionDoesNotExistError, 
            asyncpg.exceptions.InterfaceError,
            asyncpg.exceptions.ConnectionFailureError,
            asyncpg.exceptions.PostgresConnectionError,
            ConnectionResetError
        )),
        before_sleep=lambda rs: logger.warning(f"⏳ DB connect retry {rs.attempt_number}/5 after {rs.outcome.exception()}")
    )
    async def _create_pool(self):
        if not self._connection_url:
            raise RuntimeError("Database URL not configured")

        logger.info(f"🆕 Initializing unified DB pool (min={self._pool_config['min_size']}, max={self._pool_config['max_size']})")

        try:
            # asyncpg handles SSL based on sslmode in connection URL
            # No need to pass SSL context separately - asyncpg manages it
            self._pool = await asyncpg.create_pool(
                dsn=self._connection_url,
                **self._pool_config
            )
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            logger.info("✅ DB pool initialized and validated successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize DB pool: {e}")
            self._pool = None
            raise

    async def initialize(self):
        if self._pool is not None:
            return
        async with self._lock:
            if self._pool is None:
                await self._create_pool()

    async def ensure_healthy(self):
        if self._pool is None:
            await self.initialize()
            return

        now = time.time()
        if now - self._last_health_check < self._health_check_interval:
            return

        self._last_health_check = now
        try:
            async with self._pool.acquire(timeout=3.0) as conn:
                await conn.execute("SELECT 1")
        except Exception as e:
            logger.warning(f"⚠️ DB pool health check failed: {e}. Attempting recovery...")
            async with self._lock:
                try:
                    if self._pool:
                        await self._pool.close()
                except Exception as close_err:
                    logger.warning(f"⚠️ Error closing pool during recovery: {close_err}")
                finally:
                    self._pool = None
                await self._create_pool()

    @asynccontextmanager
    async def connection(self):
        await self.ensure_healthy()
        if not self._pool:
            raise RuntimeError("Database pool not available")
        
        cid = get_correlation_id()
        cid_str = f" [{cid}]" if cid else ""
        
        logger.debug(f"🔌{cid_str} Acquiring database connection...")
        
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Use longer timeout for database acquisition
                # Railway might have slow connection times, especially on startup/restart
                async with self._pool.acquire(timeout=20.0) as conn:
                    yield conn
                return
            except Exception as e:
                last_error = e
                error_str = str(e)
                exc_type = type(e).__name__
                exc_args = str(e.args) if hasattr(e, 'args') else 'N/A'
                logger.error(f"❌{cid_str} Failed to acquire DB connection (attempt {attempt + 1}/{max_retries}): {exc_type}: {error_str or exc_args}")

                # Only retry on specific errors and if we have retries left
                combined_error = f"{exc_type} {error_str}".lower()
                should_retry = (
                    attempt < max_retries - 1 and
                    any(err in combined_error for err in [
                        "event loop is closed",
                        "bad file descriptor",
                        "pool is closed",
                        "timeout",  # Retry on timeout errors
                        "connection reset",  # Retry on connection reset
                        "connection refused",  # Retry on connection refused
                        "disconnected"  # Retry on disconnect
                    ])
                )
                
                if should_retry:
                    logger.warning(f"⚠️{cid_str} Attempting to reinitialize pool due to connection issue")
                    async with self._lock:
                        try:
                            if self._pool:
                                await self._pool.close()
                        except:
                            pass
                        self._pool = None
                        await self._create_pool()
                    # Small delay before retry
                    await asyncio.sleep(0.1)
                else:
                    # Don't retry for "another operation is in progress" or other errors
                    raise
        
        # If we exhausted retries, raise the last error
        if last_error:
            raise last_error

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("🛑 DB pool closed")

    async def execute(self, query: str, *args):
        async with self.connection() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        async with self.connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        async with self.connection() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self.connection() as conn:
            return await conn.fetchval(query, *args)

@asynccontextmanager
async def get_db_connection():
    """Unified entry point for getting a DB connection with correlation logging."""
    manager = await DatabaseManager.get_instance()
    async with manager.connection() as conn:
        yield conn

async def close_databases():
    manager = await DatabaseManager.get_instance()
    await manager.close()

async def init_railway_db(url: Optional[str] = None):
    """Helper for pool initialization."""
    manager = await DatabaseManager.get_instance()
    if url:
        manager._connection_url = url
    await manager.initialize()
    return manager

# Global instance for easy access
railway_db: Optional[DatabaseManager] = None

async def get_railway_db():
    global railway_db
    if railway_db is None:
        railway_db = await DatabaseManager.get_instance()
    return railway_db
