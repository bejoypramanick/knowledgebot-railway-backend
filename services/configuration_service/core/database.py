import logging
import asyncpg
from asyncpg import exceptions as asyncpg_exceptions
from fastapi import HTTPException
from pathlib import Path
from contextlib import asynccontextmanager

from shared.db import railway_db, init_railway_db, DatabaseConnection

logger = logging.getLogger(__name__)

async def validate_database_schema(database_url: str):
    """"Check if database schema exists and is properly initialized.
    
    Note: DDL operations should only be run manually via SQL migration files.
    This function only validates schema existence.
    """
    try:
        conn = await asyncpg.connect(database_url)

        # Check if widget_configuration table exists (main schema indicator)
        widget_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'widget_configuration')"
        )

        if not widget_exists:
            logger.warning("� Database tables not found. Please run schema migrations manually.")
            logger.info("💡 Run: psql -d $DATABASE_URL < sql/schema_3nf.sql")
            project_root = Path(__file__).parent.parent.parent.parent
            schema_path = project_root / "sql" / "schema_3nf.sql"
            if schema_path.exists():
                logger.info(f"📄 Schema file available at: {schema_path}")
            else:
                logger.error(f"❌ Schema file not found: {schema_path}")
        else:
            logger.info("✅ Database tables exist and are properly initialized")

        # Check for token_usage_log table
        token_log_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'token_usage_log')"
        )

        if not token_log_exists:
            logger.warning("� token_usage_log table not found. Please run token usage migration manually.")
            logger.info("💡 Run: psql -d $DATABASE_URL < sql/add_token_usage_log_migration.sql")
            project_root = Path(__file__).parent.parent.parent.parent
            migration_path = project_root / "sql" / "add_token_usage_log_migration.sql"
            if migration_path.exists():
                logger.info(f"📄 Migration file available at: {migration_path}")
            else:
                logger.error(f"❌ Migration file not found: {migration_path}")
        else:
            logger.info("✅ token_usage_log table exists")

        await conn.close()

    except Exception as e:
        logger.error(f"❌ Database schema initialization error: {e}")
        raise

@asynccontextmanager
async def get_db_connection():
    """
    Get database connection using the pre-initialized connection pool.
    
    The database pool is initialized during service startup for optimal performance.
    """
    try:
        from shared.db import get_db_connection as shared_get_conn
        async with shared_get_conn() as conn:
            yield conn

    except RuntimeError as e:
        error_msg = str(e)
        if "returned None" in error_msg:
            logger.error("❌ Database connection pool returned None - this indicates pool corruption")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable due to connection pool corruption. Please try again."
            )
        elif "timed out" in error_msg:
            logger.error("❌ Database connection acquisition timed out")
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout. Please try again."
            )
        elif "unhealthy" in error_msg:
            logger.error("❌ Database pool health check failed")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable. Please try again."
            )
        else:
            logger.error(f"❌ Database runtime error: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable"
            )

    except asyncpg_exceptions.TooManyConnectionsError:
        logger.error("❌ Database connection pool exhausted")
        raise HTTPException(
            status_code=503,
            detail="Database connection pool exhausted. Please try again in a few moments."
        )

    except Exception as e:
        error_msg = str(e)
        # Handle specific database errors
        if "too many clients already" in error_msg.lower():
            logger.error(f"❌ Railway PostgreSQL connection limit exceeded: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database connection limit exceeded. Please wait and retry."
            )
        elif "connection timed out" in error_msg.lower() or "connection timeout" in error_msg.lower():
            logger.error(f"❌ Database connection timeout: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout. Please try again."
            )
        elif "authentication failed" in error_msg.lower():
            logger.error(f"❌ Database authentication failed")
            raise HTTPException(
                status_code=503,
                detail="Database authentication error. Please contact support."
            )
        else:
            logger.error(f"❌ Unexpected error in get_db_connection: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable"
            )
