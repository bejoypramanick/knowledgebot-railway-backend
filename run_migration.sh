#!/bin/bash

# Script to run the database migration on Railway
# This adds the missing columns to admins and human_agents tables

echo "🔄 Starting database migration..."
echo "📋 Adding profile columns to admins and human_agents tables"

# Run the migration SQL file
# You'll need to replace DATABASE_URL with your actual Railway database URL
psql "$DATABASE_URL" -f migrate_user_tables.sql

echo "✅ Migration completed!"
echo "🔍 Verifying the changes..."

# Verify the columns were added
psql "$DATABASE_URL" -c "
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name IN ('admins', 'human_agents')
AND column_name IN ('display_name', 'photo_url', 'last_login', 'preferences', 'created_at', 'updated_at')
ORDER BY table_name, column_name;
"

echo "🎉 Database migration complete!"
echo "💡 You can now test the profile endpoints"