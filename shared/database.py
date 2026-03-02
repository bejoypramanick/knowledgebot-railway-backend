"""
Unified Database Module for All Microservices

This module provides a single, consistent database manager that all microservices
in the project should use. It abstracts away asyncpg details and provides:

1. Singleton DatabaseManager instance
2. Async context manager for connections
3. Health checking
4. Automatic retries
5. Comprehensive logging

Usage in any microservice:
    from shared.database import init_db, get_db_connection, close_db

    # In lifespan/startup:
    await init_db()

    # In route/function:
    async with get_db_connection() as conn:
        result = await conn.fetch(query)

    # In shutdown:
    await close_db()
"""

import os
from typing import Optional

from shared.db import DatabaseManager, get_db_connection, close_databases
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("database", "shared")


async def init_db(database_url: Optional[str] = None) -> DatabaseManager:
    """
    Initialize the global database connection pool.

    Call this once during application startup.

    Args:
        database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.

    Returns:
        DatabaseManager instance for the application

    Raises:
        RuntimeError: If DATABASE_URL is not set and database_url is None
        Exception: If database initialization fails
    """
    db_url = database_url or os.getenv("DATABASE_URL")

    if not db_url:
        raise RuntimeError(
            "Database URL not configured. Set DATABASE_URL environment variable "
            "or pass database_url parameter to init_db()"
        )

    logger.info("🚀 Initializing database connection pool...")

    try:
        manager = await DatabaseManager.get_instance()
        if database_url:
            manager._connection_url = database_url

        await manager.initialize()
        logger.info("✅ Database initialized successfully")
        return manager

    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise


async def validate_db_schema() -> bool:
    """
    Validate that the database schema is properly initialized.

    Returns:
        True if schema is valid, False otherwise

    Raises:
        Exception: If database connection fails
    """
    logger.info("🔍 Validating database schema...")

    try:
        async with get_db_connection() as conn:
            # Simple validation: check if critical tables exist
            result = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )

            if result > 0:
                logger.info(f"✅ Database schema valid ({result} tables found)")
                return True
            else:
                logger.warning("⚠️ No tables found in database")
                return False

    except Exception as e:
        logger.error(f"❌ Schema validation failed: {e}")
        raise


async def health_check() -> dict:
    """
    Perform a health check on the database connection.

    Returns:
        dict with keys:
            - status: 'healthy' or 'unhealthy'
            - message: Human-readable status message
            - latency_ms: Time in milliseconds to perform check

    Raises:
        Exception: If health check encounters an unexpected error
    """
    import time

    start_time = time.time()

    try:
        async with get_db_connection() as conn:
            await conn.execute("SELECT 1")

        latency_ms = (time.time() - start_time) * 1000
        return {
            "status": "healthy",
            "message": "Database connection healthy",
            "latency_ms": round(latency_ms, 2),
        }

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return {
            "status": "unhealthy",
            "message": f"Database check failed: {e}",
            "latency_ms": round(latency_ms, 2),
        }


async def close_db() -> None:
    """
    Close the global database connection pool.

    Call this during application shutdown to properly clean up resources.
    """
    logger.info("🛑 Closing database connection pool...")
    try:
        await close_databases()
        logger.info("✅ Database connection pool closed")
    except Exception as e:
        logger.error(f"❌ Error closing database: {e}")
        raise


__all__ = [
    "init_db",
    "validate_db_schema",
    "health_check",
    "close_db",
    "get_db_connection",  # Re-export for convenience
]
