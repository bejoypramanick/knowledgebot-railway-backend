#!/usr/bin/env python3
"""
Simple migration runner for the knowledge bot backend.
Reads SQL migration files and applies them to the database.
"""

import asyncio
import sys
import os
from pathlib import Path
import asyncpg
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import the database configuration
sys.path.insert(0, str(Path(__file__).parent))
from shared.sqlalchemy_db import get_db_session, DATABASE_URL

async def run_migration_file(filepath: str):
    """Read and execute a single migration file."""
    print(f"\n📋 Reading migration file: {filepath}")

    try:
        with open(filepath, 'r') as f:
            sql_content = f.read()

        print(f"📋 Applying migration from: {filepath}")
        print(f"📋 Migration SQL (first 200 chars):\n{sql_content[:200]}...")

        async with get_db_session() as session:
            # Execute each statement separately since some statements need to be executed individually
            statements = sql_content.split(';')
            executed = 0

            for stmt in statements:
                stmt = stmt.strip()
                if not stmt:
                    continue

                print(f"\n  Executing: {stmt[:100]}...")
                try:
                    await session.execute(text(stmt))
                    executed += 1
                    print(f"  ✅ Success")
                except Exception as e:
                    print(f"  ⚠️  Statement failed: {e}")
                    # Continue to next statement - some may be idempotent (IF NOT EXISTS)

            await session.commit()
            print(f"\n✅ Migration applied successfully! Executed {executed} statements.")
            return True

    except Exception as e:
        print(f"\n❌ Error applying migration: {type(e).__name__}: {e}")
        return False

async def check_feedback_type_column():
    """Check if the feedback_type column exists."""
    print("\n🔍 Checking if feedback_type column exists...")

    query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'chat_sessions'
            AND column_name = 'feedback_type'
        ) as column_exists
    """

    try:
        async with get_db_session() as session:
            result = await session.execute(text(query))
            row = result.fetchone()

            if row:
                exists = row[0] if isinstance(row, tuple) else row['column_exists']
                if exists:
                    print("✅ feedback_type column EXISTS")
                else:
                    print("❌ feedback_type column DOES NOT EXIST")
                return exists
            else:
                print("⚠️  Could not determine if column exists")
                return False
    except Exception as e:
        print(f"❌ Error checking column: {e}")
        return False

async def main():
    """Main migration runner."""
    print("🚀 Knowledge Bot Migration Runner")
    print(f"📦 Database URL: {DATABASE_URL}")

    # Check if feedback_type column already exists
    exists = await check_feedback_type_column()

    if exists:
        print("\n✅ Migration already applied! Column exists.")
        return True

    # Run the migration
    migration_file = Path(__file__).parent / "sql" / "migrations" / "add_feedback_type_to_chat_sessions.sql"

    if not migration_file.exists():
        print(f"\n❌ Migration file not found: {migration_file}")
        return False

    success = await run_migration_file(str(migration_file))

    if success:
        # Verify the column was created
        print("\n🔍 Verifying migration...")
        exists = await check_feedback_type_column()
        if exists:
            print("\n✅ Migration verified successfully!")
            return True
        else:
            print("\n⚠️  Migration completed but column not found")
            return False

    return False

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
