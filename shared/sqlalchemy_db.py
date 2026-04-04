"""
SQLAlchemy-based Database Manager for All Microservices

Uses SQLAlchemy 2.0+ with async support for battle-tested connection pooling
and database operations. This replaces custom asyncpg wrapper with industry-
standard proven solution used by Fortune 500 companies.

Features:
- AsyncAdaptedQueuePool for production-grade connection management
- Automatic connection recycling and health checks (pre-ping)
- Proper pool sizing with overflow for burst traffic
- Connection timeouts and circuit breaker patterns
- Comprehensive logging and monitoring
- Works with both raw SQL and SQLAlchemy ORM
- High-availability configuration for Railway/cloud deployments

Usage:
    from shared.sqlalchemy_db import init_database, get_db_session, close_database

    # Startup
    await init_database()

    # In endpoints/tasks
    async with get_db_session() as session:
        result = await session.execute(select(User))

    # Shutdown
    await close_database()
"""

import os
import asyncio
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy import text
from sqlalchemy.pool import AsyncAdaptedQueuePool

from shared.otel_logger import get_otel_logger
from shared.tenant_context import (
    get_current_tenant_id,
    get_current_tenant_slug,
    get_current_user_email,
    get_current_user_role_id,
)

logger = get_otel_logger("sqlalchemy_db", "shared")

# Global engine and session factory
_engine = None
_async_session_maker = None


async def _apply_request_context(conn_or_session) -> None:
    tenant_id = get_current_tenant_id() or ""
    tenant_slug = get_current_tenant_slug() or ""
    user_role_id = get_current_user_role_id() or ""
    user_email = get_current_user_email() or ""

    await conn_or_session.execute(
        text(
            """
            SELECT
                set_config('app.current_tenant_id', :tenant_id, true),
                set_config('app.current_tenant_slug', :tenant_slug, true),
                set_config('app.current_user_role_id', :user_role_id, true),
                set_config('app.current_user_email', :user_email, true)
            """
        ),
        {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "user_role_id": user_role_id,
            "user_email": user_email,
        },
    )


async def init_database(database_url: Optional[str] = None, max_retries: int = 5) -> None:
    """
    Initialize SQLAlchemy async engine with exponential backoff for cold starts.

    🚀 Railway Serverless Optimization ("The Gentle Wake-up")

    CRITICAL: Use INTERNAL URL, not public URL!
    - ✅ DATABASE_URL=postgresql://...railway.internal:5432/... (internal network)
    - ❌ DATABASE_URL=postgresql://...railway.app:5432/... (goes to internet!)

    Connection pooling for serverless:
    - pool_size=3 (not 10) - Prevents overwhelming cold-booting DB
    - Multiple services × pool_size = total connections. Keep each service small!

    Service staggering strategy (important!):
    1. Start database first
    2. Wait 30 seconds for DB to stabilize
    3. Start configuration service only (let it warm up)
    4. Once healthy, start remaining services (api_gateway, chatbot_orchestration, etc)

    Environment variables:
    - DATABASE_URL: PostgreSQL connection (MUST use railway.internal, not public URL!)
    - DB_POOL_SIZE: Min connections (default: 3 for serverless)
    - DB_POOL_MAX_OVERFLOW: Burst connections (default: 2)
    - DB_POOL_RECYCLE: Recycle stale connections after 3600s
    - DB_CONNECT_TIMEOUT: Connection timeout in seconds (default: 60)
    - DB_COMMAND_TIMEOUT: Command timeout in seconds (default: 20)

    Features:
    - Exponential backoff: 1s → 2s → 4s → 8s → 16s retries
    - Per-attempt timeout: 70s (generous for cold-start)
    - pool_pre_ping=True: Connection health checks
    - pool_recycle=3600s: Prevents stale connections
    - Fails fast if DB unreachable (container crash → auto-restart)

    Args:
        database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.
        max_retries: Maximum retry attempts (default: 5)

    Raises:
        RuntimeError: If DATABASE_URL is not set or all retries exhausted
    """
    global _engine, _async_session_maker

    db_url = database_url or os.getenv("DATABASE_URL")

    if not db_url:
        raise RuntimeError(
            "Database URL not configured. Set DATABASE_URL environment variable "
            "or pass database_url to init_database()"
        )

    # Convert to async SQLAlchemy URL format
    if db_url.startswith("postgresql://"):
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        async_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    else:
        async_url = db_url

    # Read Railway environment configuration
    # IMPORTANT: Use SMALL pool_size for serverless/cold-start scenarios
    # If 5 services each have pool_size=10, that's 50+ connections hitting DB at startup
    # Railway hobby tier often has 20-50 max connections total
    pool_size = int(os.getenv("DB_POOL_SIZE", "3"))  # Reduced from 10 to 3 for serverless
    pool_max_overflow = int(os.getenv("DB_POOL_MAX_OVERFLOW", "2"))  # Reduced from 10 to 2
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    statement_timeout = os.getenv("DB_STATEMENT_TIMEOUT", "60000")
    connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "60"))  # 60s for cold-start resilience
    command_timeout = int(os.getenv("DB_COMMAND_TIMEOUT", "20"))

    logger.info("🚀 Initializing SQLAlchemy async engine with cold-start retry logic...")
    logger.info(f"📊 Pool: size={pool_size}, overflow={pool_max_overflow}, recycle={pool_recycle}s")
    logger.info(f"⏱️  Timeouts: connect={connect_timeout}s, command={command_timeout}s, statement={statement_timeout}ms")

    # SSL configuration for Railway
    # Internal URLs (railway.internal) don't need SSL — they're on a private network.
    # Disabling SSL for internal connections eliminates "SSL error: unexpected eof"
    # log spam from unclean connection teardowns during pool recycling.
    # External/public URLs should use SSL for security.
    ssl_mode = os.getenv("DB_SSL_MODE", "auto")
    if ssl_mode == "auto":
        # Auto-detect: disable SSL for internal Railway network, require for external
        if "railway.internal" in db_url:
            ssl_setting = "disable"
        else:
            ssl_setting = "require"
    else:
        ssl_setting = ssl_mode  # Allow explicit override: disable, require, prefer, etc.

    logger.info(f"🔒 SSL mode: {ssl_setting} (configured: {ssl_mode})")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 Connection attempt {attempt}/{max_retries}")

            # Add per-attempt timeout with generous buffer for serverless cold-start
            # Cold-booting PostgreSQL on shared tier can be slow, especially with network latency
            attempt_timeout = connect_timeout + 10  # 70s total timeout

            async with asyncio.timeout(attempt_timeout):
                # Build connect_args with SSL configuration
                connect_args = {
                    "timeout": connect_timeout,
                    "command_timeout": command_timeout,
                    "server_settings": {
                        "application_name": "knowledgebot_service",
                        "statement_timeout": statement_timeout,
                        # PG18: JIT for complex analytics queries
                        "jit": "on",
                        # PG18: SSD-optimized cost model
                        "random_page_cost": "1.1",
                        # PG18: Async I/O prefetch for sequential scans (io_uring backend)
                        "effective_io_concurrency": "200",
                        # PG18: Maintenance operations async prefetch
                        "maintenance_io_concurrency": "100",
                    },
                }

                # Configure SSL: disable for internal Railway network to avoid
                # "SSL error: unexpected eof while reading" on connection recycling
                if ssl_setting == "disable":
                    connect_args["ssl"] = False
                elif ssl_setting == "require":
                    import ssl as ssl_module
                    ssl_ctx = ssl_module.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl_module.CERT_NONE
                    connect_args["ssl"] = ssl_ctx

                # Create async engine with AsyncAdaptedQueuePool
                # PG18: asyncpg natively uses async I/O; server-side io_method='worker'
                # is configured via ALTER SYSTEM in the migration script.
                _engine = create_async_engine(
                    async_url,
                    echo=False,
                    poolclass=AsyncAdaptedQueuePool,
                    pool_size=pool_size,
                    max_overflow=pool_max_overflow,
                    pool_recycle=pool_recycle,
                    pool_pre_ping=True,  # Health check before using connections
                    echo_pool=False,
                    connect_args=connect_args,
                )

                # NOTE: PG18 skip scan is automatic — the planner uses it via
                # cost-based optimization when a B-tree multicolumn index has
                # low-cardinality leading columns. No GUC parameter exists.

                # Create async session factory
                _async_session_maker = async_sessionmaker(
                    _engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                    autocommit=False,
                )

                # Test connection with timeout
                async with _engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))

            logger.info("✅ SQLAlchemy engine initialized successfully")
            logger.info(f"📊 Production pool: min={pool_size}, max={pool_size + pool_max_overflow}, "
                       f"recycle={pool_recycle}s, pre_ping=True")
            return

        except asyncio.TimeoutError as e:
            last_error = e
            logger.error(f"❌ Attempt {attempt}/{max_retries} timeout (>{attempt_timeout}s): {e}")

            if attempt < max_retries:
                wait_time = 2 ** (attempt - 1)
                logger.info(f"⏳ Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"❌ All {max_retries} attempts timed out. Container will exit.")
                raise RuntimeError(f"Database connection timeout after {max_retries} attempts")

        except Exception as e:
            last_error = e
            logger.error(f"❌ Attempt {attempt}/{max_retries} failed: {e}")

            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                wait_time = 2 ** (attempt - 1)
                logger.info(f"⏳ Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                # All retries exhausted - let container crash (fail fast)
                logger.error(f"❌ All {max_retries} connection attempts failed. Container will exit.")
                raise RuntimeError(
                    f"Failed to connect to database after {max_retries} attempts. Last error: {last_error}"
                )


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session for queries as an async context manager.

    Use as an async context manager:
        async with get_db_session() as session:
            result = await session.execute(query)

    The session is automatically returned to the pool on exit.

    Yields:
        AsyncSession instance

    Raises:
        RuntimeError: If database not initialized
        Exception: If connection fails
    """
    if _async_session_maker is None:
        raise RuntimeError(
            "Database not initialized. Call init_database() first."
        )

    session = None
    import time
    start_time = time.time()
    
    try:
        session = _async_session_maker()
        async with session:
            await _apply_request_context(session)
            yield session
            
        # Log slow session usage (held for more than 5 seconds)
        duration = time.time() - start_time
        if duration > 5.0:
            logger.warning(f"⚠️ Slow database session: held for {duration:.2f}s")
            
    except asyncio.CancelledError:
        # Handle request cancellation gracefully
        logger.warning("⚠️ Database session cancelled (likely due to request timeout)")
        if session:
            try:
                await session.rollback()
            except Exception:
                pass  # Ignore errors during cancellation cleanup
        raise
    except Exception as e:
        if session:
            await session.rollback()
        logger.error(f"Database error: {e}")
        raise


@asynccontextmanager
async def get_db_connection():
    """
    Get a raw asyncpg connection from the SQLAlchemy engine pool.

    Use for code that needs raw asyncpg features (conn.fetchrow, $1 params, etc.):
        async with get_db_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    The connection is automatically returned to the pool on exit.
    """
    if _engine is None:
        raise RuntimeError(
            "Database not initialized. Call init_database() first."
        )

    # Get raw asyncpg connection from SQLAlchemy's async engine pool
    async with _engine.connect() as sa_conn:
        await _apply_request_context(sa_conn)
        raw_conn = await sa_conn.get_raw_connection()
        yield raw_conn.dbapi_connection.driver_connection


async def health_check() -> dict:
    """
    Perform database health check with connection pool stats.

    Returns:
        dict with status, latency, and pool statistics
    """
    import time

    start = time.time()

    try:
        if _engine is None:
            return {
                "status": "unhealthy",
                "message": "Database engine not initialized",
                "latency_ms": 0,
            }

        async with _engine.connect() as conn:
            result = await conn.execute(text("SELECT current_setting('server_version') AS version"))
            pg_version = result.scalar()

        latency_ms = (time.time() - start) * 1000

        # Get connection pool statistics
        pool = _engine.pool
        pool_stats = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
        }
        
        # Log pool stats if connections are getting exhausted
        if pool.checkedout() > pool.size() * 0.8:
            logger.warning(f"⚠️ Connection pool usage high: {pool_stats}")
        
        return {
            "status": "healthy",
            "message": "Database connection healthy",
            "latency_ms": round(latency_ms, 2),
            "pg_version": pg_version,
            "pool": pool_stats,
        }

    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        return {
            "status": "unhealthy",
            "message": f"Database check failed: {e}",
            "latency_ms": round(latency_ms, 2),
        }


async def close_database() -> None:
    """
    Close database engine and dispose of all connections.

    Call during application shutdown.
    """
    global _engine

    if _engine is None:
        return

    logger.info("🛑 Closing SQLAlchemy database engine...")

    try:
        await _engine.dispose()
        _engine = None
        logger.info("✅ Database engine closed")
    except Exception as e:
        logger.error(f"❌ Error closing database: {e}")
        raise


async def execute_autocommit(sql: str) -> None:
    """
    Execute a statement outside a transaction (AUTOCOMMIT).

    Required for commands like VACUUM that are not allowed inside a transaction block.
    """
    global _engine

    if not sql or not sql.strip():
        return

    if _engine is None:
        await init_database()

    async with _engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        await _apply_request_context(conn)
        await conn.execute(text(sql))


async def validate_database() -> bool:
    """
    Validate database schema exists.

    Returns:
        True if schema is valid
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
            )
            count = result.scalar()

            if count > 0:
                logger.info(f"✅ Database schema valid ({count} tables)")
                return True
            else:
                logger.warning("⚠️ No tables found in database")
                return False

    except Exception as e:
        logger.error(f"❌ Schema validation failed: {e}")
        return False


__all__ = [
    "init_database",
    "get_db_session",
    "get_db_connection",
    "health_check",
    "close_database",
    "execute_autocommit",
    "validate_database",
]
