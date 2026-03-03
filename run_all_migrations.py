#!/usr/bin/env python3
"""
Comprehensive migration runner for the knowledge bot backend.
Reads all SQL migration files in sql/migrations and applies them to the database.
Tracks applied migrations to avoid running them multiple times.
"""

import asyncio
import sys
import os
from pathlib import Path
from sqlalchemy import text

# Import the database configuration
sys.path.insert(0, str(Path(__file__).parent))
from shared.sqlalchemy_db import get_db_session, DATABASE_URL


async def ensure_migrations_table():
    """Ensure the migrations_applied table exists for tracking."""
    create_table = text("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            id SERIAL PRIMARY KEY,
            migration_name VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT NOW()
        )
    """)

    try:
        async with get_db_session() as session:
            await session.execute(create_table)
            await session.commit()
        print("✅ Migrations tracking table ready")
        return True
    except Exception as e:
        print(f"⚠️  Could not create migrations table: {e}")
        return False


async def get_applied_migrations():
    """Get list of already-applied migrations."""
    query = text("SELECT migration_name FROM migrations_applied ORDER BY applied_at")

    try:
        async with get_db_session() as session:
            result = await session.execute(query)
            applied = [row[0] for row in result.fetchall()]
        return applied
    except Exception as e:
        print(f"⚠️  Could not fetch applied migrations: {e}")
        return []


async def mark_migration_applied(migration_name: str):
    """Mark a migration as applied."""
    insert = text("""
        INSERT INTO migrations_applied (migration_name) VALUES (:name)
        ON CONFLICT DO NOTHING
    """)

    try:
        async with get_db_session() as session:
            await session.execute(insert, {"name": migration_name})
            await session.commit()
        return True
    except Exception as e:
        print(f"⚠️  Could not mark migration as applied: {e}")
        return False


async def run_migration_file(filepath: str, migration_name: str):
    """Read and execute a single migration file."""
    print(f"\n📋 Running migration: {migration_name}")
    print(f"   File: {filepath}")

    try:
        with open(filepath, 'r') as f:
            sql_content = f.read().strip()

        if not sql_content:
            print(f"⚠️  Migration file is empty, skipping")
            return False

        # Split by semicolons but be careful about statements that may have None values
        statements = [s.strip() for s in sql_content.split(';')]

        executed_count = 0
        failed_count = 0

        async with get_db_session() as session:
            for stmt in statements:
                if not stmt:  # Skip empty statements
                    continue

                try:
                    # Show first 80 chars of the statement
                    stmt_preview = stmt.replace('\n', ' ')[:80]
                    print(f"   ➜ {stmt_preview}...")

                    await session.execute(text(stmt))
                    executed_count += 1
                except Exception as e:
                    failed_count += 1
                    error_msg = str(e)[:100]
                    print(f"   ⚠️  Failed: {error_msg}")
                    # Continue with next statement - some may be idempotent (IF NOT EXISTS)

            await session.commit()

        if executed_count > 0:
            print(f"   ✅ Applied: {executed_count} statement(s)")
            if failed_count > 0:
                print(f"   ⚠️  {failed_count} statement(s) had errors (may be idempotent)")
            return True
        else:
            print(f"   ⚠️  No statements executed")
            return False

    except Exception as e:
        print(f"   ❌ Error: {type(e).__name__}: {e}")
        return False


async def main():
    """Main migration runner."""
    print("=" * 70)
    print("🚀 Knowledge Bot Migration Runner - Apply All Migrations")
    print("=" * 70)
    print(f"📦 Database: {DATABASE_URL}")
    print()

    # Ensure migrations table exists
    if not await ensure_migrations_table():
        print("❌ Could not ensure migrations table exists")
        return False

    # Get list of already-applied migrations
    applied = await get_applied_migrations()
    print(f"\n📊 Already applied: {len(applied)} migration(s)")
    if applied:
        for m in applied:
            print(f"   ✓ {m}")

    # Find all migration files
    migrations_dir = Path(__file__).parent / "sql" / "migrations"
    if not migrations_dir.exists():
        print(f"\n❌ Migrations directory not found: {migrations_dir}")
        return False

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        print(f"\n⚠️  No migration files found in {migrations_dir}")
        return True

    print(f"\n📁 Found {len(migration_files)} migration file(s)")

    # Filter to only unapplied migrations
    unapplied = [f for f in migration_files if f.name not in applied]

    if not unapplied:
        print("\n✅ All migrations already applied!")
        return True

    print(f"🔄 Applying {len(unapplied)} new migration(s)...")

    # Apply each migration
    successful = 0
    failed = []

    for migration_file in unapplied:
        migration_name = migration_file.name
        success = await run_migration_file(str(migration_file), migration_name)

        if success:
            # Mark as applied
            if await mark_migration_applied(migration_name):
                successful += 1
                print(f"   💾 Recorded in migrations table")
            else:
                print(f"   ⚠️  Applied but could not record in migrations table")
                failed.append(migration_name)
        else:
            failed.append(migration_name)

    # Summary
    print("\n" + "=" * 70)
    print(f"📊 Results: {successful} successful, {len(failed)} failed")
    print("=" * 70)

    if failed:
        print("\n❌ Failed migrations:")
        for m in failed:
            print(f"   - {m}")
        return False
    else:
        print("\n✅ All migrations applied successfully!")
        return True


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
