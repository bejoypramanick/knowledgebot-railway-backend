# Database Migrations

This directory contains SQL migration scripts to add **only the missing tables and columns** to the KnowledgeBot database.

## What's Already in the Main Schema

The main `database_schema.sql` already includes these tables:
- ✅ `admins` (missing `status` column)
- ✅ `human_agents` 
- ✅ `users`
- ✅ `chat_sessions`
- ✅ `chat_messages`
- ✅ `session_assignments` (uses user_role_id FK to user_role_mapping)
- ✅ `file_uploads`
-- ✅ `configuration_metadata`
-- ✅ `widget_configuration`
-- ✅ `widget_suggested_messages`
-- ✅ `security_settings`
-- ✅ `llm_providers`
-- ✅ `persona_configurations`
- ✅ `notifications`
- ✅ `chat_feedback`
- ✅ `token_usage_log`
- ✅ `metrics`
- ✅ `email_oauth_credentials`
- ✅ `user_unique_ids`
- ✅ `scraped_websites`
- ✅ `api_usage`
- ✅ `widget_scripts`

## Migration Files (Missing Elements Only)

### 001_add_admins_status_column.sql
- **Adds**: `status` column to existing `admins` table
- **Required for**: User role management and admin status tracking
- **Fixes**: Missing `status` column that causes role detection issues

### 002_create_chatbot_personas_table.sql
- **Creates**: `chatbot_personas` table (completely missing)
- **Required for**: Chatbot persona switching functionality
- **Fixes**: `relation "chatbot_personas" does not exist` error

### 003_create_agent_session_assignments_table.sql
- **Creates**: `agent_session_assignments` table (missing proper FK structure)
- **Required for**: Human agent assignments using agent_id FK
- **Fixes**: Missing table for proper agent-to-session relationships

### 004_update_master_migration_script.sql
- **Purpose**: Master script to run only the missing migrations
- **Includes**: Verification queries to check what exists vs what's missing

## How to Run Migrations

### Option 1: Run All Missing Migrations
```bash
psql $DATABASE_URL -f sql/migrations/004_update_master_migration_script.sql
```

### Option 2: Run Individual Migrations
```bash
# Run specific migration
psql $DATABASE_URL -f sql/migrations/001_add_admins_status_column.sql

# Run in order
for file in sql/migrations/00*.sql; do
    echo "Running $file..."
    psql $DATABASE_URL -f "$file"
done
```

### Option 3: Run via Railway Console
1. Connect to your PostgreSQL database in Railway
2. Copy and paste the contents of `004_update_master_migration_script.sql`
3. Execute the script

## What These Migrations Fix

### Before Migrations:
```sql
❌ admins.status column missing → User role detection fails
❌ chatbot_personas table missing → Persona switching fails  
❌ agent_session_assignments table missing → Agent assignments fail
```

### After Migrations:
```sql
✅ admins.status column added → User role detection works
✅ chatbot_personas table created → Persona switching works
✅ agent_session_assignments table created → Agent assignments work
```

## Verification

After running migrations, you can verify:

```sql
-- Check missing tables were created
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN ('chatbot_personas', 'agent_session_assignments');

-- Check admins table has status column
SELECT column_name FROM information_schema.columns 
WHERE table_schema = 'public' AND table_name = 'admins' AND column_name = 'status';

-- Check all existing tables (should show 22 tables)
SELECT COUNT(*) as total_tables FROM information_schema.tables 
WHERE table_schema = 'public';
```

## Important Notes

- **Safe Migration Design**: All scripts use `IF NOT EXISTS` to prevent errors
- **Minimal Impact**: Only adds what's missing, doesn't touch existing tables
- **Proper Constraints**: Foreign keys, CHECK constraints, and indexes included
- **Default Data**: Includes default persona and admin status updates
- **Audit Trail**: Added `created_at`, `updated_at`, and email tracking where appropriate

## Dependencies

- PostgreSQL 12+ (uses uuid-ossp extension)
- Existing tables from `database_schema.sql` must exist first
- The migrations assume the base schema is already applied
