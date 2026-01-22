#!/bin/bash

# Script to run database migrations
# Usage: ./run_migrations.sh

set -e

echo "🔄 Running database migrations..."

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ DATABASE_URL environment variable not set"
    echo "Please set DATABASE_URL to your PostgreSQL connection string"
    exit 1
fi

# Run the migrations in order
echo "📊 Running migration: 20250122_update_pending_to_confirmed.sql"
psql "$DATABASE_URL" -f migrations/20250122_update_pending_to_confirmed.sql

echo "🗑️  Running migration: 20250122_remove_unused_columns.sql"
psql "$DATABASE_URL" -f migrations/20250122_remove_unused_columns.sql

echo "✅ All migrations completed successfully!"
echo ""
echo "The following columns have been removed:"
echo "- status (from admins and human_agents tables)"
echo "- confirmation_token (from admins and human_agents tables)"
echo "- auto_generated_password (from admins and human_agents tables)"
echo "- confirmed_at (from admins and human_agents tables)"
echo ""
echo "Admin and human agent roles will now activate immediately when added to configuration."