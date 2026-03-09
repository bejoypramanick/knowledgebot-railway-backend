"""
Centralized database initialization with retry logic for Railway deployment.

On Railway, PostgreSQL may be starting up during container restarts.
This module provides reliable database connection with exponential backoff retry.

Usage:
    # Instead of:
    # await init_database(database_url)

    # Use:
    from shared.db_retry import initialize_database_with_retry
    success = await initialize_database_with_retry(database_url)
"""

import asyncio
import logging
from typing import Optional
from shared.sqlalchemy_db import init_database, validate_database

logger = logging.getLogger(__name__)


async def initialize_database_with_retry(
    database_url: str,
    max_retries: int = 5,
    retry_delay: int = 2,
    service_name: str = "unknown"
) -> bool:
    """
    Initialize database with retry logic for Railway deployments.

    Handles PostgreSQL startup delays during container restarts with exponential backoff.

    Args:
        database_url: PostgreSQL connection URL
        max_retries: Number of connection attempts (default: 5)
        retry_delay: Delay between retries in seconds (default: 2)
        service_name: Service name for logging context

    Returns:
        bool: True if database initialized and validated successfully, False otherwise

    Example:
        ```python
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            success = await initialize_database_with_retry(database_url, service_name="my-service")
            if success:
                logger.info("Database ready")
            else:
                logger.warning("Database unavailable, but service started")
        ```
    """
    if not database_url:
        logger.warning("❌ DATABASE_URL not set - database will not be available")
        return False

    logger.info(f"💾 [{service_name}] Initializing SQLAlchemy database with retry logic...")
    logger.info(f"   Max retries: {max_retries}, Retry delay: {retry_delay}s")

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 [{service_name}] Database connection attempt {attempt}/{max_retries}")

            # Try to initialize database
            await init_database(database_url)
            logger.info(f"✅ [{service_name}] SQLAlchemy engine initialized")

            # Validate schema
            is_valid = await validate_database()
            if is_valid:
                logger.info(f"✅ [{service_name}] Database schema validated successfully")
                logger.info(f"✅ [{service_name}] Database is ready and operational")
                return True
            else:
                logger.warning(f"⚠️ [{service_name}] Database schema validation returned False")

                if attempt < max_retries:
                    logger.info(f"⏳ [{service_name}] Retrying in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                continue

        except Exception as e:
            logger.error(f"❌ [{service_name}] Database connection attempt {attempt} failed: {e}")

            if attempt < max_retries:
                logger.info(f"⏳ [{service_name}] Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"❌ [{service_name}] All {max_retries} connection attempts failed")
                logger.warning(f"⚠️ [{service_name}] Service starting with database unavailable")
                return False

    return False
