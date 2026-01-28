# Database Migrations

This directory contains SQL migration scripts to add missing tables and columns to the KnowledgeBot database.

## Migration Files

### 001_add_missing_columns.sql
- Adds `status` column to `admins` table
- Adds constraints and indexes for the new column
- **Required for**: User role management and admin status tracking

### 002_create_chatbot_personas_table.sql
- Creates `chatbot_personas` table for managing AI personas
- Includes default "KnowledgeBot" persona
- **Required for**: Chatbot persona switching functionality

### 003_create_security_settings_table.sql
- Creates `security_settings` table for application configuration
- Includes default security settings
- **Required for**: Security and configuration management

### 004_create_llm_providers_table.sql
- Creates `llm_providers` table for tracking token usage
- Includes default providers (Gemini, OpenAI, Anthropic, Local)
- **Required for**: Token usage tracking and limits

### 005_create_agent_session_assignments_table.sql
- Creates `agent_session_assignments` table for human agent assignments
- **Required for**: Human agent session management

### 006_create_suggested_messages_table.sql
- Creates `suggested_messages` table for chat widget suggestions
- Includes default suggested messages
- **Required for**: Chat widget UI functionality

### 007_create_widget_configuration_table.sql
- Creates `widget_configuration` table for chat widget settings
- Includes default widget configuration
- **Required for**: Chat widget customization

### 008_create_all_migrations_script.sql
- Master script to run all migrations in order
- Includes verification queries
- **Use this to apply all migrations at once**

## How to Run Migrations

### Option 1: Run All Migrations at Once
```bash
psql $DATABASE_URL -f sql/migrations/008_create_all_migrations_script.sql
```

### Option 2: Run Individual Migrations
```bash
# Run specific migration
psql $DATABASE_URL -f sql/migrations/001_add_missing_columns.sql

# Run in order
for file in sql/migrations/00*.sql; do
    echo "Running $file..."
    psql $DATABASE_URL -f "$file"
done
```

### Option 3: Run via Railway Console
1. Connect to your PostgreSQL database in Railway
2. Copy and paste the contents of `008_create_all_migrations_script.sql`
3. Execute the script

## Verification

After running migrations, you can verify the tables were created:

```sql
-- Check all new tables
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'chatbot_personas', 'security_settings', 'llm_providers',
        'agent_session_assignments', 'suggested_messages', 'widget_configuration'
    );

-- Check admins table has status column
SELECT column_name FROM information_schema.columns 
WHERE table_schema = 'public' AND table_name = 'admins' AND column_name = 'status';
```

## Important Notes

- All migrations use `IF NOT EXISTS` to prevent errors if tables already exist
- Foreign key constraints are properly defined
- Default data is inserted for all tables
- Updated_at triggers are created for audit trails
- All tables include proper comments for documentation

## Dependencies

- PostgreSQL 12+ (uses uuid-ossp extension)
- Existing tables: `admins`, `human_agents`, `chat_sessions`
- The migrations assume the base schema from `database_schema.sql` exists
