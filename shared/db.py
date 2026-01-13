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
    
    async def connect(self, min_size: int = 5, max_size: int = 20, server_timeout: int = 60):
        """Create connection pool with retry logic and serverless optimization."""
        for attempt in range(3):
            try:
                self._pool = await asyncpg.create_pool(
                    self.connection_url,
                    min_size=min_size,    # Serverless: start with 5 connections
                    max_size=max_size,    # Serverless: max 20 connections
                    server_settings={
                        'application_name': 'knowledgebot_config_service',
                        'timezone': 'UTC',
                    },
                    command_timeout=server_timeout,  # Serverless: 60 second timeout
                    setup=lambda conn: conn.add_log_listener(
                        lambda record: logger.debug(f"PostgreSQL log: {record}")
                    )
                )
                # Only log success if pool is actually created
                if self._pool is not None:
                    try:
                        redacted = self.connection_url
                        # Redact password if present
                        if '//' in redacted and '@' in redacted:
                            prefix, rest = redacted.split('//', 1)
                            creds, host = rest.split('@', 1)
                            if ':' in creds:
                                user, _pwd = creds.split(':', 1)
                                redacted = f"{prefix}//{user}:***@{host}"
                        logger.info(f"✅ Database connection pool created successfully ({redacted}) - min_size={min_size}, max_size={max_size}")
                    except Exception:
                        logger.info("✅ Database connection pool created successfully (connection URL redaction failed)")
                    return  # Success - exit retry loop
                else:
                    logger.error("❌ Pool creation returned None - retrying...")
                    
            except Exception as e:
                if attempt == 2:  # Last attempt
                    logger.error(f"❌ Failed to create database connection pool after 3 attempts: {e}")
                    logger.debug(f"Connection URL: {self.connection_url}")
                    raise
                else:
                    logger.warning(f"⚠️ Pool creation attempt {attempt + 1} failed, retrying: {e}")
                    await asyncio.sleep(1)  # Brief delay before retry
    
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
    """Initialize Railway PostgreSQL database connection with serverless optimization."""
    global railway_db
    
    # If railway_db already exists and has a healthy pool, reuse it
    if railway_db is not None:
        if hasattr(railway_db, '_pool') and railway_db._pool is not None:
            # Test pool health before reusing
            try:
                async with railway_db._pool.acquire() as conn:
                    await conn.execute("SELECT 1")  # Health check
                logger.debug("✅ Reusing existing healthy Railway database connection pool")
                return railway_db
            except Exception as e:
                logger.warning(f"⚠️ Existing pool health check failed: {e}")
                logger.info("🔄 Creating new connection pool...")
                # Close old pool and create new one
                try:
                    await railway_db.disconnect()
                except:
                    pass  # Ignore errors during cleanup
        
        # If it exists but has no pool, try to connect it
        if hasattr(railway_db, 'connection_url') and railway_db.connection_url == connection_url:
            logger.info("🔄 Railway database instance exists but pool is missing, attempting to connect...")
            try:
                await railway_db.connect(min_size=5, max_size=20)  # Production-optimized
                return railway_db
            except Exception as e:
                logger.warning(f"⚠️ Failed to connect existing instance: {e}")
    
    # Create new database instance with serverless-optimized settings
    logger.info("🆕 Creating new Railway database connection pool (serverless optimized)")
    railway_db = Database(connection_url=connection_url)
    await railway_db.connect(min_size=5, max_size=20)  # Production-optimized
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

