"""Database initialization for Health Monitoring Service."""
import logging
from shared.db import get_db_connection

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Initializes and validates health monitoring database schema."""

    @staticmethod
    async def initialize_and_validate(db_url: str) -> None:
        """Initialize database and create tables if they don't exist."""
        try:
            # Create service_health_checks table if it doesn't exist
            await DatabaseInitializer._create_service_health_checks_table()
            logger.info("✅ Database schema validated/created successfully")
        except Exception as e:
            logger.error(f"❌ Error initializing database: {e}")
            raise

    @staticmethod
    async def _create_service_health_checks_table() -> None:
        """Create service_health_checks table if it doesn't exist."""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS public.service_health_checks (
            id SERIAL PRIMARY KEY,
            service_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL,
            response_time_ms INTEGER,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            error_message TEXT,
            metadata JSONB
        );

        CREATE INDEX IF NOT EXISTS idx_service_health_checks_service_checked
            ON public.service_health_checks(service_name, checked_at DESC);

        CREATE INDEX IF NOT EXISTS idx_service_health_checks_checked_at
            ON public.service_health_checks(checked_at DESC);

        CREATE INDEX IF NOT EXISTS idx_service_health_checks_status
            ON public.service_health_checks(status);
        """

        try:
            logger.log_db_operation("Creating service_health_checks table")
            async with get_db_connection() as conn:
                await conn.execute(create_table_query)
                logger.info("✅ service_health_checks table created/validated")
        except Exception as e:
            logger.error(f"❌ Error creating service_health_checks table: {e}")
            raise


# Global instance for easy access
database_initializer = DatabaseInitializer()
