#!/bin/bash

# Railway Project Migration Script
# This script helps migrate between Railway projects

set -e  # Exit on any error

# Configuration
SOURCE_PROJECT_ID="19719468-25dc-4b99-9715-5a0540bca7f4"
TARGET_PROJECT_ID="0ed75b44-58cd-47b0-9520-6888f4592121"
BACKUP_DIR="./railway_migration_backup_$(date +%Y%m%d_%H%M%S)"
REPO_NAME="knowledgebot-railway-backend"

echo "🚂 Railway Project Migration Script"
echo "===================================="
echo "Source Project: $SOURCE_PROJECT_ID"
echo "Target Project: $TARGET_PROJECT_ID"
echo "Backup Directory: $BACKUP_DIR"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

echo "📦 Step 1: Installing Railway CLI..."
if ! command -v railway &> /dev/null; then
    echo "Installing Railway CLI..."
    npm install -g @railway/cli
else
    echo "Railway CLI already installed"
fi

echo ""
echo "🔐 Step 2: Authenticating with Railway..."
railway login

echo ""
echo "🔗 Step 3: Linking to source project..."
railway link --project "$SOURCE_PROJECT_ID"

echo ""
echo "💾 Step 4: Creating database backup..."
echo "Creating full database backup..."
railway run pg_dump --no-owner --no-privileges > full_backup.sql

echo "Creating schema-only backup..."
railway run pg_dump --schema-only --no-owner --no-privileges > schema_backup.sql

echo "Creating data-only backup..."
railway run pg_dump --data-only --no-owner --no-privileges > data_backup.sql

echo ""
echo "📋 Step 5: Exporting environment variables..."
railway variables > environment_variables.txt

echo ""
echo "✅ Backup completed successfully!"
echo "Backup files created in: $BACKUP_DIR"
ls -la *.sql *.txt

echo ""
echo "📝 Next Steps (Manual):"
echo "1. Create new Railway project from GitHub repo: $REPO_NAME"
echo "2. Link to target project: railway link $TARGET_PROJECT_ID"
echo "3. Configure environment variables from environment_variables.txt"
echo "4. Restore database: railway run psql < full_backup.sql"
echo "5. Test the application"
echo ""

echo "🔄 To continue with target project setup, run:"
echo "cd .."
echo "railway link --project $TARGET_PROJECT_ID"
echo "railway run psql < $BACKUP_DIR/full_backup.sql"

echo ""
echo "⚠️  IMPORTANT: Test thoroughly before deleting source project!"
echo "Keep source project running until migration is fully verified."