#!/usr/bin/env python3
"""
Migration script to add zoom and position fields to widget_configuration table.
This script runs the SQL migration for widget zoom and position fields.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db import init_railway_db, close_databases
from shared.utils import validate_environment, wait_for_railway_network

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_migration():
    """Run the widget zoom and position migration."""
    try:
        logger.info("🚀 Starting widget zoom/position migration...")

        # Validate environment
        validate_environment()

        # Wait for network
        await wait_for_railway_network()

        # Initialize database
        db = await init_railway_db()
        logger.info("✅ Database connection established")

        # Read migration SQL
        migration_path = Path(__file__).parent.parent / "sql" / "add_widget_zoom_position_migration.sql"
        if not migration_path.exists():
            raise FileNotFoundError(f"Migration file not found: {migration_path}")

        migration_sql = migration_path.read_text()
        logger.info("📄 Migration SQL loaded")

        # Execute migration
        async with db.acquire() as conn:
            await conn.execute(migration_sql)
            logger.info("✅ Migration executed successfully")

        # Verify the migration by checking if the new columns exist
        async with db.acquire() as conn:
            columns = await conn.fetch("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'widget_configuration'
                AND column_name IN ('profile_zoom', 'chat_icon_zoom', 'profile_position', 'chat_icon_position')
                ORDER BY column_name
            """)

            column_names = [row['column_name'] for row in columns]
            expected_columns = {'profile_zoom', 'chat_icon_zoom', 'profile_position', 'chat_icon_position'}

            if expected_columns.issubset(set(column_names)):
                logger.info(f"✅ Migration verified! Added columns: {', '.join(sorted(expected_columns))}")
            else:
                missing = expected_columns - set(column_names)
                logger.warning(f"⚠️ Some columns may not have been added: {missing}")

        logger.info("🎉 Widget zoom/position migration completed successfully!")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise
    finally:
        await close_databases()

if __name__ == "__main__":
    asyncio.run(run_migration())