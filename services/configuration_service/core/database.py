import logging
import asyncpg
from asyncpg import exceptions as asyncpg_exceptions
from fastapi import HTTPException
from pathlib import Path
from contextlib import asynccontextmanager

from shared.db import railway_db, init_railway_db, DatabaseConnection

logger = logging.getLogger(__name__)

async def init_database_schema(database_url: str):
    """Initialize database schema if tables don't exist"""
    try:
        conn = await asyncpg.connect(database_url)

        # Check if widget_configuration table exists (main schema indicator)
        widget_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'widget_configuration')"
        )

        if not widget_exists:
            logger.info("📊 Database tables not found, initializing schema...")

            # Read and execute schema
            # Adjust path: currently in services/configuration_service/core/database.py
            # Go up 3 levels to project root? No, local root is project root.
            # __file__ is /.../services/configuration_service/core/database.py
            # schema is in sql/schema_3nf.sql (relative to project root)
            
            project_root = Path(__file__).parent.parent.parent.parent
            schema_path = project_root / "sql" / "schema_3nf.sql"
            
            if schema_path.exists():
                schema_sql = schema_path.read_text()
                await conn.execute(schema_sql)
                logger.info("✅ Database schema initialized successfully")
            else:
                logger.warning(f"⚠️ Schema file not found: {schema_path}")
        else:
            logger.info("✅ Database tables already exist")

        # Check for token_usage_log table (added later) and create if missing
        token_log_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'token_usage_log')"
        )

        if not token_log_exists:
            logger.info("📊 token_usage_log table not found, creating...")

            # Read and execute token usage log migration
            migration_path = project_root / "add_token_usage_log_migration.sql"
            if migration_path.exists():
                migration_sql = migration_path.read_text()
                await conn.execute(migration_sql)
                logger.info("✅ token_usage_log table created successfully")
            else:
                logger.warning(f"⚠️ Token usage migration file not found: {migration_path}")

                # Create table directly if migration file not found
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS token_usage_log (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
                        message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE,
                        provider VARCHAR(50) NOT NULL,
                        model VARCHAR(100),
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_cents INTEGER DEFAULT 0,
                        api_call_type VARCHAR(50),
                        request_metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_session ON token_usage_log(session_id);
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider ON token_usage_log(provider);
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_created_at ON token_usage_log(created_at DESC);
                    COMMENT ON TABLE token_usage_log IS 'Detailed token usage log for correlating usage with specific API calls';
                """)
                logger.info("✅ token_usage_log table created directly")
        else:
            logger.info("✅ token_usage_log table already exists")

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
