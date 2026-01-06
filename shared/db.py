"""Shared database utilities for PostgreSQL connections."""
import asyncpg
import os
import logging
from typing import Optional
from contextlib import asynccontextmanager
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class Database:
    """Database connection manager for PostgreSQL."""
    
    def __init__(self, connection_url: str):
        """
        Initialize database connection.
        
        Args:
            connection_url: Full PostgreSQL connection URL (e.g., postgresql://user:pass@host:port/db)
        """
        self.connection_url = connection_url
        self._pool: Optional[asyncpg.Pool] = None
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
    async def connect(self, min_size: int = 5, max_size: int = 20):
        """Create connection pool with retry logic."""
        try:
            self._pool = await asyncpg.create_pool(
                self.connection_url,
                min_size=min_size,
                max_size=max_size,
                command_timeout=30
            )
            # Log pool creation and redact connection URL for diagnostics
            try:
                redacted = self.connection_url
                # Redact password if present
                if '//' in redacted and '@' in redacted:
                    prefix, rest = redacted.split('//', 1)
                    creds, host = rest.split('@', 1)
                    if ':' in creds:
                        user, _pwd = creds.split(':', 1)
                        redacted = f"{prefix}//{user}:***@{host}"
                logger.info("Database connection pool created successfully (%s)", redacted)
            except Exception:
                logger.info("Database connection pool created successfully (connection URL redaction failed)")
        except Exception as e:
            logger.error(f"Failed to create database connection pool: {e}")
            logger.debug("Connection URL: %s", self.connection_url)
            raise
    
    async def disconnect(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Database connection pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool."""
        if not self._pool:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        async with self._pool.acquire() as connection:
            yield connection
    
    async def execute(self, query: str, *args):
        """Execute a query."""
        async with self.acquire() as conn:
            try:
                return await conn.execute(query, *args)
            except Exception as e:
                logger.exception("DB execute failed. Query: %s Args: %s", query, args)
                raise
    
    async def fetch(self, query: str, *args):
        """Fetch rows from a query."""
        async with self.acquire() as conn:
            try:
                return await conn.fetch(query, *args)
            except Exception as e:
                logger.exception("DB fetch failed. Query: %s Args: %s", query, args)
                raise
    
    async def fetchrow(self, query: str, *args):
        """Fetch a single row from a query."""
        async with self.acquire() as conn:
            try:
                return await conn.fetchrow(query, *args)
            except Exception as e:
                logger.exception("DB fetchrow failed. Query: %s Args: %s", query, args)
                raise
    
    async def fetchval(self, query: str, *args):
        """Fetch a single value from a query."""
        async with self.acquire() as conn:
            try:
                return await conn.fetchval(query, *args)
            except Exception as e:
                logger.exception("DB fetchval failed. Query: %s Args: %s", query, args)
                raise


# Global database instances
railway_db: Optional[Database] = None
neon_db: Optional[Database] = None


async def init_railway_db(connection_url: str):
    """Initialize Railway PostgreSQL database connection."""
    global railway_db
    railway_db = Database(connection_url=connection_url)
    await railway_db.connect()
    return railway_db


async def init_neon_db(connection_url: str):
    """Initialize Neon DB connection."""
    global neon_db
    neon_db = Database(connection_url=connection_url)
    await neon_db.connect()
    return neon_db


async def close_databases():
    """Close all database connections."""
    global railway_db, neon_db
    if railway_db:
        await railway_db.disconnect()
    if neon_db:
        await neon_db.disconnect()

