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

logger = get_otel_logger("sqlalchemy_db", "shared")

# Global engine and session factory
_engine = None
_async_session_maker = None


async def init_database(database_url: Optional[str] = None) -> None:
    """
    Initialize SQLAlchemy async engine with connection pooling.

    Uses Railway environment configuration:
    - DATABASE_URL: PostgreSQL connection string
    - RAILWAY_PRIVATE_IP: For internal service-to-service communication

    Pool configuration from environment (with production defaults):
    - DB_POOL_SIZE: Min connections kept alive (default: 5, production: 10-20)
    - DB_POOL_MAX_OVERFLOW: Additional connections for burst traffic (default: 3, production: 5-10)
    - DB_POOL_RECYCLE: Recycle stale connections after N seconds (default: 3600)
    - DB_STATEMENT_TIMEOUT: Query timeout in ms (default: 60000, production: 30000-120000)
    - DB_CONNECT_TIMEOUT: Connection timeout in seconds (default: 10, production: 10-15)
    - DB_COMMAND_TIMEOUT: Command timeout in seconds (default: 20, production: 20-30)

    Production-grade configuration:
    - Uses AsyncAdaptedQueuePool for robust async connection management
    - pool_pre_ping=True enables automatic connection health checks
    - Automatic reconnection on stale/dead connections
    - Connection recycling prevents PostgreSQL timeout issues

    Args:
        database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.

    Raises:
        RuntimeError: If DATABASE_URL is not set
        Exception: If database connection fails
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

    # Read Railway environment configuration with production-appropriate defaults
    # Increased from 5/3 to 10/10 to handle concurrent requests better
    pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
    pool_max_overflow = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    statement_timeout = os.getenv("DB_STATEMENT_TIMEOUT", "60000")
    connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    command_timeout = int(os.getenv("DB_COMMAND_TIMEOUT", "20"))

    logger.info("🚀 Initializing SQLAlchemy async engine with Railway configuration...")
    logger.info(f"📊 Pool: size={pool_size}, overflow={pool_max_overflow}, recycle={pool_recycle}s")
    logger.info(f"⏱️  Timeouts: connect={connect_timeout}s, command={command_timeout}s, statement={statement_timeout}ms")

    try:
        # Create async engine with AsyncAdaptedQueuePool for production robustness
        _engine = create_async_engine(
            async_url,
            echo=False,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=pool_size,
            max_overflow=pool_max_overflow,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,  # Verify connections before using (critical for production)
            echo_pool=False,
            connect_args={
                "timeout": connect_timeout,
                "command_timeout": command_timeout,
                "server_settings": {
                    "application_name": "knowledgebot_service",
                    "statement_timeout": statement_timeout,
                },
            },
        )

        # Create async session factory
        _async_session_maker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        # Test connection
        async with _engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

        logger.info("✅ SQLAlchemy engine initialized successfully")
        logger.info(f"📊 Production pool config: min={pool_size}, max={pool_size + pool_max_overflow}, "
                   f"recycle={pool_recycle}s, pre_ping=True")

    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise


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
    try:
        session = _async_session_maker()
        async with session:
            yield session
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


async def health_check() -> dict:
    """
    Perform database health check.

    Returns:
        dict with status and latency
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
            await conn.execute(text("SELECT 1"))

        latency_ms = (time.time() - start) * 1000
        return {
            "status": "healthy",
            "message": "Database connection healthy",
            "latency_ms": round(latency_ms, 2),
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
    "health_check",
    "close_database",
    "validate_database",
]
