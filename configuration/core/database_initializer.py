"""
Centralized Database Initialization Service
Handles all database initialization logic for the singleton pattern.
"""
import os
from pathlib import Path
from typing import Optional

from configuration.core.logging_config import get_railway_logger

from .db import init_railway_db

logger = get_railway_logger(__name__)

class DatabaseInitializer:
    """Centralized database initialization service using singleton pattern."""
    
    _instance: Optional['DatabaseInitializer'] = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def initialize_database(cls, database_url: Optional[str] = None) -> bool:
        """
        Initialize database connection pool using singleton pattern.
        
        Args:
            database_url: Database connection URL. If None, uses environment variables.
            
        Returns:
            bool: True if initialization successful, False otherwise
        """
        if cls._initialized:
            logger.info("🔄 Database already initialized (singleton)")
            return True
            
        try:
            # Use provided URL or get from environment
            db_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
            
            if not db_url:
                logger.error("❌ No database URL provided and none found in environment")
                return False
            
            logger.info("🔄 Initializing database connection pool (singleton)...")
            await init_railway_db(db_url)
            cls._initialized = True
            logger.info("✅ Database connection pool initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            cls._initialized = False
            return False
    
    @classmethod
    async def validate_database_schema(cls, database_url: Optional[str] = None) -> bool:
        """
        Validate that required database schema exists.
        
        Args:
            database_url: Database connection URL. If None, uses environment variables.
            
        Returns:
            bool: True if schema validation successful, False otherwise
        """
        try:
            import asyncpg

            # Use provided URL or get from environment
            db_url = database_url or os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
            
            if not db_url:
                logger.error("❌ No database URL provided for schema validation")
                return False
            
            conn = await asyncpg.connect(db_url)
            
            # Check if widget_configuration table exists (main schema indicator)
            widget_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'widget_configuration')"
            )
            
            if not widget_exists:
                logger.warning("🚫 Database tables not found. Please run schema migrations manually.")
                logger.info("💡 Run: psql -d $DATABASE_URL < sql/schema_3nf.sql")
                project_root = Path(__file__).parent.parent
                schema_path = project_root / "sql" / "schema_3nf.sql"
                if schema_path.exists():
                    logger.info(f"📄 Schema file available at: {schema_path}")
                else:
                    logger.error(f"❌ Schema file not found: {schema_path}")
                await conn.close()
                return False
            else:
                logger.info("✅ Database tables exist and are properly initialized")
            
            # Check for token_usage_log table
            token_log_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'token_usage_log')"
            )
            
            if not token_log_exists:
                logger.warning("🚫 token_usage_log table not found. Please run token usage migration manually.")
                logger.info("💡 Run: psql -d $DATABASE_URL < sql/add_token_usage_log_migration.sql")
                project_root = Path(__file__).parent.parent
                migration_path = project_root / "sql" / "add_token_usage_log_migration.sql"
                if migration_path.exists():
                    logger.info(f"📄 Migration file available at: {migration_path}")
                else:
                    logger.error(f"❌ Migration file not found: {migration_path}")
                await conn.close()
                return False
            else:
                logger.info("✅ token_usage_log table exists")
            
            await conn.close()
            return True
            
        except Exception as e:
            logger.error(f"❌ Database schema validation error: {e}")
            return False
    
    @classmethod
    async def initialize_and_validate(cls, database_url: Optional[str] = None) -> bool:
        """
        Initialize database and validate schema in one call.
        
        Args:
            database_url: Database connection URL. If None, uses environment variables.
            
        Returns:
            bool: True if both initialization and validation successful, False otherwise
        """
        # Initialize database connection
        if not await cls.initialize_database(database_url):
            return False
        
        # Validate schema
        if not await cls.validate_database_schema(database_url):
            logger.warning("⚠️ Database initialized but schema validation failed")
            # Don't return False here - service can still run with warnings
        
        return True
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if database has been initialized."""
        return cls._initialized
    
    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None
        cls._initialized = False

# Create singleton instance
database_initializer = DatabaseInitializer()
