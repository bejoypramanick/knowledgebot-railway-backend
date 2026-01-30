#!/bin/bash

# Script to run migration 004_fix_missing_columns_and_tables.sql
# This fixes the missing columns and tables causing database errors

echo "🚀 Running migration 004: Fix missing columns and tables..."

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL environment variable is not set"
    exit 1
fi

# Run the migration
psql "$DATABASE_URL" -f sql/migrations/004_fix_missing_columns_and_tables.sql

if [ $? -eq 0 ]; then
    echo "✅ Migration 004 completed successfully"
else
    echo "❌ Migration 004 failed"
    exit 1
fi
