#!/bin/bash

# Railway Environment Variables Extractor
# This script extracts environment variables from ALL Railway projects

set -e  # Exit on any error

# Configuration
SOURCE_PROJECT_ID="19719468-25dc-4b99-9715-5a0540bca7f4"
TARGET_PROJECT_ID="0ed75b44-58cd-47b0-9520-6888f4592121"
BACKUP_DIR="./railway_env_backup_$(date +%Y%m%d_%H%M%S)"
REPO_NAME="knowledgebot-railway-backend"

echo "🚂 Railway Environment Variables Extractor"
echo "==========================================="
echo "This script will extract environment variables from ALL your Railway projects"
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
echo "📋 Step 5: Exporting environment variables from ALL projects..."

# Create variables directory
mkdir -p "$BACKUP_DIR/variables"

# Get list of all projects
echo "Getting list of all Railway projects..."
railway list --json > "$BACKUP_DIR/all_projects.json"

# Extract project information and export variables from each project
echo "Exporting variables from all projects..."

# Use a more robust approach to parse JSON and extract project IDs
if command -v jq &> /dev/null; then
    # If jq is available, use it for better JSON parsing
    PROJECTS=$(cat "$BACKUP_DIR/all_projects.json" | jq -r '.[] | select(.id != null) | .id')
else
    # Fallback to basic parsing
    PROJECTS=$(cat "$BACKUP_DIR/all_projects.json" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
fi

echo "Found projects: $PROJECTS"

# Export variables from each project
for PROJECT_ID in $PROJECTS; do
    echo "Exporting variables from project: $PROJECT_ID"

    # Link to project
    railway link --project "$PROJECT_ID" 2>/dev/null

    # Get project info
    if command -v jq &> /dev/null; then
        PROJECT_NAME=$(railway status --json 2>/dev/null | jq -r '.name // "project_'${PROJECT_ID}'"')
    else
        PROJECT_NAME=$(railway status --json 2>/dev/null | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -z "$PROJECT_NAME" ]; then
            PROJECT_NAME="project_$PROJECT_ID"
        fi
    fi

    # Export variables in different formats
    railway variables > "$BACKUP_DIR/variables/${PROJECT_NAME}_${PROJECT_ID}_variables.txt" 2>/dev/null || echo "Failed to export variables for $PROJECT_NAME"

    # Export variables in JSON format for easier parsing
    railway variables --json > "$BACKUP_DIR/variables/${PROJECT_NAME}_${PROJECT_ID}_variables.json" 2>/dev/null || echo "Failed to export JSON variables for $PROJECT_NAME"

    echo "✓ Exported variables for: $PROJECT_NAME ($PROJECT_ID)"
done

# Go back to source project for database operations
echo "Returning to source project for database operations..."
railway link --project "$SOURCE_PROJECT_ID"

# Create summary
echo "Environment Variables Summary" > "$BACKUP_DIR/variables/README.md"
echo "==============================" >> "$BACKUP_DIR/variables/README.md"
echo "" >> "$BACKUP_DIR/variables/README.md"
echo "This directory contains environment variables from all your Railway projects." >> "$BACKUP_DIR/variables/README.md"
echo "" >> "$BACKUP_DIR/variables/README.md"
echo "Files:" >> "$BACKUP_DIR/variables/README.md"
ls -1 "$BACKUP_DIR/variables/" | while read file; do
    echo "- $file" >> "$BACKUP_DIR/variables/README.md"
done
echo "" >> "$BACKUP_DIR/variables/README.md"
echo "Format:" >> "$BACKUP_DIR/variables/README.md"
echo "- *_variables.txt: Human-readable format" >> "$BACKUP_DIR/variables/README.md"
echo "- *_variables.json: JSON format for scripting" >> "$BACKUP_DIR/variables/README.md"
echo "" >> "$BACKUP_DIR/variables/README.md"
echo "To restore variables to a project:" >> "$BACKUP_DIR/variables/README.md"
echo "1. Link to target project: railway link --project <PROJECT_ID>" >> "$BACKUP_DIR/variables/README.md"
echo "2. Set variables: railway variables --set KEY=VALUE" >> "$BACKUP_DIR/variables/README.md"

echo ""
echo "✅ Backup completed successfully!"
echo "Backup files created in: $BACKUP_DIR"
echo ""
echo "📁 Environment Variables Exported:"
ls -la "$BACKUP_DIR/variables/"
echo ""

echo "📝 Usage Instructions:"
echo "1. Review exported variables in: $BACKUP_DIR/variables/"
echo "2. Use the JSON files for programmatic access"
echo "3. Use the TXT files for manual review"
echo "4. Import variables to new projects using: railway variables --set KEY=VALUE"
echo ""

echo "🔄 For project migration:"
echo "1. Create new Railway project from GitHub repo: $REPO_NAME"
echo "2. Link to target project: railway link --project $TARGET_PROJECT_ID"
echo "3. Configure environment variables from the exported files"
echo "4. Restore database if needed: railway run psql < database_backup.sql"

echo ""
echo "⚠️  IMPORTANT: Test thoroughly before deleting source project!"
echo "Keep source project running until migration is fully verified."