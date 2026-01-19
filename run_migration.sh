#!/bin/bash

# Script to run the database migration on Railway
# This ensures required indexes exist on admins and human_agents tables

echo "🔄 Starting database migration..."
echo "📋 Ensuring required indexes exist on admins and human_agents tables"

# Run the migration SQL file
# You'll need to replace DATABASE_URL with your actual Railway database URL
psql "$DATABASE_URL" -f migrate_user_tables.sql

echo "✅ Migration completed!"
echo "🔍 Verifying the changes..."

# Verify the indexes were created
psql "$DATABASE_URL" -c "
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename IN ('admins', 'human_agents')
AND indexname LIKE '%email%status%'
ORDER BY tablename, indexname;
"

echo "🎉 Database migration complete!"
echo "💡 Profile endpoints now use Firebase data instead of stored columns"