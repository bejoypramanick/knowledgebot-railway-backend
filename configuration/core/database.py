import logging
import asyncio
from shared.config import settings
from shared.db import init_railway_db, railway_db

logger = logging.getLogger(__name__)

# Lazy database initialization for serverless optimization
async def get_railway_db():
    """Get Railway database connection, initializing if needed."""
    try:
        from shared.db import DatabaseManager
        manager = await DatabaseManager.get_instance()
        
        # Ensure it's initialized
        if manager._pool is None and settings.railway_postgres_url:
            logger.info("🔄 Lazy initializing Railway PostgreSQL database...")
            manager._connection_url = settings.railway_postgres_url
            await manager.initialize()
            logger.info("✅ Railway PostgreSQL database initialized")
        
        return manager
    except Exception as e:
        logger.error(f"❌ Failed to initialize Railway PostgreSQL database: {e}")
        raise

async def get_db_connection():
    """Context manager for getting a database connection."""
    from shared.db import get_db_connection as shared_get_conn
    async with shared_get_conn() as conn:
        yield conn
