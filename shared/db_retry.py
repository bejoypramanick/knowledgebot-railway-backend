"""
Database Initialization with Retry Logic using Tenacity

Replaces manual retry loops with battle-tested Tenacity library.
Handles PostgreSQL startup delays on Railway deployments with exponential backoff.

Usage:
    from shared.db_retry import initialize_database_with_retry
    success = await initialize_database_with_retry(database_url, service_name="my-service")
"""

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import init_database, validate_database

logger = get_otel_logger(__name__, "shared")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _init_database_with_retry(database_url: str) -> None:
    """Internal database initialization with Tenacity retry decorator."""
    await init_database(database_url)
    is_valid = await validate_database()
    if not is_valid:
        raise RuntimeError("Database schema validation returned False")


async def initialize_database_with_retry(
    database_url: str,
    max_retries: int = 5,
    retry_delay: int = 2,  # Ignored when using Tenacity (kept for API compatibility)
    service_name: str = "unknown",
) -> bool:
    """
    Initialize database with exponential backoff retry logic for Railway deployments.

    Handles PostgreSQL startup delays during container restarts.

    Args:
        database_url: PostgreSQL connection URL
        max_retries: Number of connection attempts (default: 5, overridden by Tenacity config)
        retry_delay: Ignored (kept for backward compatibility)
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
        ```
    """
    if not database_url:
        logger.warning("❌ DATABASE_URL not set - database will not be available")
        return False

    logger.info(f"💾 [{service_name}] Initializing SQLAlchemy database with retry logic...")
    logger.info(f"   Retries: up to 5 with exponential backoff (2s-30s)")

    try:
        await _init_database_with_retry(database_url)
        logger.info(f"✅ [{service_name}] Database is ready and operational")
        return True
    except RetryError as e:
        logger.error(f"❌ [{service_name}] All retry attempts failed: {e.last_attempt.exception()}")
        logger.warning(f"⚠️ [{service_name}] Service starting with database unavailable")
        return False
    except Exception as e:
        logger.error(f"❌ [{service_name}] Database initialization failed: {e}")
        logger.warning(f"⚠️ [{service_name}] Service starting with database unavailable")
        return False
