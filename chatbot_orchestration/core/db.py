"""Shared database utilities for PostgreSQL connections."""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential

from chatbot_orchestration.core.logging_config import get_railway_logger
from shared.correlation_id import get_correlation_id

logger = get_railway_logger(__name__)

class DatabaseManager:
    """Robust database connection pool manager with health checks and auto-recovery."""
    
    _instance: Optional['DatabaseManager'] = None
    _lock = asyncio.Lock()

    def __init__(self, connection_url: Optional[str] = None):
        self._pool: Optional[asyncpg.Pool] = None
        self._connection_url = connection_url or os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
        self._pool_config = {
            'min_size': 2,
            'max_size': 20,
            'command_timeout': 60.0,
            'server_settings': {
                'timezone': 'UTC',
                'application_name': 'knowledgebot_backend'
            }
        }
        self._last_health_check = 0
        self._health_check_interval = 30  # seconds

    @classmethod
    async def get_instance(cls) -> 'DatabaseManager':
        """Get or create the singleton instance of DatabaseManager."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = DatabaseManager()
        return cls._instance

    def configure(self, **kwargs):
        """Configure pool settings before initialization."""
        if 'min_size' in kwargs:
            self._pool_config['min_size'] = kwargs['min_size']
        if 'max_size' in kwargs:
            self._pool_config['max_size'] = kwargs['max_size']
        if 'command_timeout' in kwargs:
            self._pool_config['command_timeout'] = kwargs['command_timeout']
        if 'application_name' in kwargs:
            self._pool_config['server_settings']['application_name'] = kwargs['application_name']

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=1, max=10),
        retry=lambda e: isinstance(e, (ConnectionRefusedError, OSError, asyncpg.exceptions.ConnectionDoesNotExistError, asyncpg.exceptions.InterfaceError)),
        before_sleep=lambda rs: logger.warning(f"⏳ DB connect retry {rs.attempt_number}/5...")
    )
    async def _create_pool(self):
        """Internal method to create the pool."""
        if not self._connection_url:
            raise RuntimeError("Database URL not configured")
        
        # Redact URL for logging
        redacted_url = self._connection_url
        if '@' in redacted_url:
            try:
                parts = redacted_url.split('@')
                cred_parts = parts[0].split(':')
                if len(cred_parts) > 2:
                    redacted_url = f"{cred_parts[0]}:***@{parts[1]}"
            except:
                redacted_url = "redacted_url"

        logger.info(f"🆕 Initializing DB pool (min={self._pool_config['min_size']}, max={self._pool_config['max_size']})")
        
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._connection_url,
                **self._pool_config
            )
            # Basic validation
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            logger.info("✅ DB pool initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create DB pool: {e}")
            self._pool = None
            raise

    async def initialize(self):
        """Carefully initialize the pool if not already done."""
        if self._pool is not None:
            return

        async with self._lock:
            if self._pool is None:
                await self._create_pool()

    async def ensure_healthy(self):
        """Ensure the pool is alive, recreate if broken."""
        if self._pool is None:
            await self.initialize()
            return

        now = asyncio.get_event_loop().time()
        if now - self._last_health_check < self._health_check_interval:
            return

        self._last_health_check = now
        try:
            async with self._pool.acquire(timeout=5.0) as conn:
                await conn.execute("SELECT 1")
        except Exception as e:
            logger.warning(f"⚠️ DB pool health check failed: {e}. Attempting recovery...")
            async with self._lock:
                await self.close()
                await self._create_pool()

    @asynccontextmanager
    async def connection(self):
        """Standard connection context manager."""
        await self.ensure_healthy()
        if not self._pool:
            raise RuntimeError("Database pool not available")
            
        async with self._pool.acquire() as conn:
            yield conn

    async def close(self):
        """Close the pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("🛑 DB pool closed")

    # Utility methods that use the connection context
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

# Standard entry point for all services
@asynccontextmanager
async def get_db_connection():
    """Single source of truth for getting a DB connection with correlation ID logging."""
    correlation_id = get_correlation_id()
    manager = await DatabaseManager.get_instance()
    
    if correlation_id:
        logger.info(f"🔍 [{correlation_id}] Acquiring database connection")
    
    async with manager.connection() as conn:
        if correlation_id:
            logger.info(f"🔍 [{correlation_id}] Database connection acquired")
        yield conn
        
    if correlation_id:
        logger.info(f"🔍 [{correlation_id}] Database connection released")

# Initialization helper
async def init_railway_db(url: Optional[str] = None):
    """Legacy helper for compatibility, now uses DatabaseManager."""
    manager = await DatabaseManager.get_instance()
    if url:
        manager._connection_url = url
    await manager.initialize()
    return manager

# Global instance for easy access where context manager isn't used
# (Initialized on first use/get_instance)
railway_db: Optional[DatabaseManager] = None

async def get_railway_db():
    global railway_db
    if railway_db is None:
        railway_db = await DatabaseManager.get_instance()
    return railway_db

# Compatibility for direct DatabaseConnection usage
class DatabaseConnection:
    """Legacy context manager for database connections."""
    async def __aenter__(self):
        self.manager = await DatabaseManager.get_instance()
        self._ctx = self.manager.connection()
        self._conn = await self._ctx.__aenter__()
        return self._conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._ctx.__aexit__(exc_type, exc_val, exc_tb)

async def close_databases():
    """Global cleanup."""
    manager = await DatabaseManager.get_instance()
    await manager.close()
