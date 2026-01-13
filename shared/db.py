"""Shared database utilities for PostgreSQL connections."""
import asyncpg
import os
import logging
import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class DatabasePool:
    """Enhanced database connection pool manager with health checks and auto-recovery."""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._dsn: Optional[str] = None
        self._pool_config: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._health_check_interval = 30  # seconds
        self._last_health_check = 0

    async def initialize_pool(
        self,
        dsn: str,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: float = 60.0,
        server_settings: Optional[Dict[str, str]] = None
    ) -> None:
        """Initialize the database connection pool with Railway optimizations."""
        async with self._lock:
            if self._pool is not None:
                await self.close_pool()

            self._dsn = dsn
            self._pool_config = {
                'min_size': min_size,
                'max_size': max_size,
                'command_timeout': command_timeout,
                'server_settings': server_settings or {}
            }

            # Add Railway-specific optimizations
            self._pool_config['server_settings'].update({
                'timezone': 'UTC',
                'application_name': 'knowledgebot_configuration_service',
                # Railway serverless optimizations
                'tcp_keepalives_idle': '60',
                'tcp_keepalives_interval': '10',
                'tcp_keepalives_count': '3'
            })

            await self._create_pool()

    async def _create_pool(self) -> None:
        """Create a new connection pool."""
        try:
            logger.info("🆕 Creating new Railway database connection pool (serverless optimized)")
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                **self._pool_config
            )

            # Test the pool immediately
            if await self._test_pool_health():
                try:
                    redacted = self._dsn
                    # Redact password if present
                    if '//' in redacted and '@' in redacted:
                        prefix, rest = redacted.split('//', 1)
                        creds, host = rest.split('@', 1)
                        if ':' in creds:
                            user, _pwd = creds.split(':', 1)
                            redacted = f"{prefix}//{user}:***@{host}"
                    logger.info(f"✅ Database connection pool created successfully ({redacted}) - min_size={self._pool_config['min_size']}, max_size={self._pool_config['max_size']}")
                except Exception:
                    logger.info("✅ Database connection pool created successfully (connection URL redaction failed)")
            else:
                raise RuntimeError("Pool health check failed immediately after creation")

        except Exception as e:
            logger.error(f"❌ Failed to create database connection pool: {e}")
            self._pool = None
            raise

    async def _test_pool_health(self) -> bool:
        """Test if the pool is healthy by acquiring and releasing a connection."""
        if self._pool is None:
            return False

        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Pool health check failed: {e}")
            return False

    async def acquire(self) -> asyncpg.Connection:
        """Acquire a database connection with health checks and None handling."""
        # Check pool health before acquiring
        if not await self._ensure_pool_health():
            raise RuntimeError("Database pool is unhealthy and could not be recovered")

        if self._pool is None:
            raise RuntimeError("Database pool is not initialized")

        try:
            # Acquire connection with timeout
            conn = await asyncio.wait_for(
                self._pool.acquire(),
                timeout=10.0
            )

            # Double-check that we got a valid connection
            if conn is None:
                logger.error("❌ Pool.acquire() returned None - pool corruption detected")
                # Try to recreate the pool
                await self._recreate_pool_on_failure()
                raise RuntimeError("Database connection pool returned None - pool corrupted")

            return conn

        except asyncio.TimeoutError:
            logger.error("⏰ Database connection acquisition timed out")
            await self._recreate_pool_on_failure()
            raise RuntimeError("Database connection acquisition timed out")

        except Exception as e:
            logger.error(f"❌ Failed to acquire database connection: {e}")
            await self._recreate_pool_on_failure()
            raise

    async def _ensure_pool_health(self) -> bool:
        """Ensure the pool is healthy, recreate if necessary."""
        current_time = asyncio.get_event_loop().time()

        # Skip health check if recently performed
        if current_time - self._last_health_check < self._health_check_interval:
            return self._pool is not None

        self._last_health_check = current_time

        if self._pool is None:
            logger.info("🔄 Pool is None, attempting to recreate...")
            try:
                await self._create_pool()
                return True
            except Exception as e:
                logger.error(f"❌ Failed to recreate pool: {e}")
                return False

        # Test pool health
        if not await self._test_pool_health():
            logger.warning("⚠️ Existing pool health check failed: object NoneType can't be used in 'await' expression")
            logger.info("🔄 Creating new connection pool...")
            try:
                await self._create_pool()
                return True
            except Exception as e:
                logger.error(f"❌ Failed to recreate unhealthy pool: {e}")
                return False

        return True

    async def _recreate_pool_on_failure(self) -> None:
        """Recreate the pool when acquisition fails."""
        try:
            if self._pool is not None:
                logger.info("🔄 Database connection pool closed")
                await self.close_pool()

            logger.info("🔄 Railway database instance exists but pool is missing, attempting to connect...")
            await self._create_pool()

        except Exception as e:
            logger.error(f"❌ Failed to recreate pool after acquisition failure: {e}")
            self._pool = None

    async def close_pool(self) -> None:
        """Close the database connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.error(f"❌ Error closing database pool: {e}")
            finally:
                self._pool = None

    @property
    def pool(self) -> Optional[asyncpg.Pool]:
        """Get the current pool instance."""
        return self._pool

    async def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics."""
        if self._pool is None:
            return {"status": "not_initialized"}

        try:
            stats = {
                "status": "healthy",
                "min_size": self._pool_config.get('min_size', 0),
                "max_size": self._pool_config.get('max_size', 0),
                "current_size": len(self._pool._holders) if hasattr(self._pool, '_holders') else 0,
                "available_connections": self._pool._queue.qsize() if hasattr(self._pool, '_queue') else 0
            }
            return stats
        except Exception as e:
            return {"status": "error", "error": str(e)}


class Database:
    """Legacy database connection manager for PostgreSQL - updated with fixes."""

    def __init__(self, connection_url: str):
        """
        Initialize database connection.

        Args:
            connection_url: Full PostgreSQL connection URL (e.g., postgresql://user:pass@host:port/db)
        """
        self.connection_url = connection_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self, min_size: int = 5, max_size: int = 20, server_timeout: int = 60):
        """Create connection pool with enhanced error handling and Railway optimization."""
        try:
            # Use the new DatabasePool for enhanced functionality
            pool_manager = DatabasePool()
            await pool_manager.initialize_pool(
                dsn=self.connection_url,
                min_size=min_size,
                max_size=max_size,
                command_timeout=server_timeout,
                server_settings={
                    'application_name': 'knowledgebot_config_service',
                    'timezone': 'UTC',
                    'tcp_keepalives_idle': '60',
                    'tcp_keepalives_interval': '10',
                    'tcp_keepalives_count': '3'
                }
            )
            self._pool = pool_manager.pool
        except Exception as e:
            logger.error(f"❌ Failed to create database connection pool: {e}")
            logger.debug(f"Connection URL: {self.connection_url}")
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


# Context manager for database connections
class DatabaseConnection:
    """Context manager for database connections."""

    def __init__(self):
        self._conn: Optional[asyncpg.Connection] = None

    async def __aenter__(self) -> asyncpg.Connection:
        # Use the pre-initialized Database class with proper acquire method
        global railway_db
        
        # If pool is not available, try to initialize it
        if railway_db is None or not hasattr(railway_db, '_pool') or railway_db._pool is None:
            logger.error("❌ Database pool not available - attempting to initialize")
            from shared.db import init_railway_db
            database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
            if database_url:
                railway_db = await init_railway_db(database_url)
                logger.info("✅ Database pool initialized in DatabaseConnection")
            else:
                raise RuntimeError("Database URL not configured")
        
        # Use the Database class's pool directly to get a connection
        if railway_db and hasattr(railway_db, '_pool') and railway_db._pool:
            self._conn = await railway_db._pool.acquire()
        else:
            raise RuntimeError("Database pool is not available for connection")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._conn is not None:
            try:
                # Return connection to pool
                if railway_db and hasattr(railway_db, '_pool'):
                    await railway_db._pool.release(self._conn)
                logger.debug("Database connection released")
            except Exception as e:
                logger.warning(f"Error releasing database connection: {e}")


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

