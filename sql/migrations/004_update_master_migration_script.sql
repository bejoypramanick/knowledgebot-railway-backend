-- Updated Master migration script to run only missing migrations
-- Execute this script to apply only the tables that don't exist in the main schema

-- Migration 001: Add missing columns to existing tables
\i 001_add_admins_status_column.sql

-- Migration 002: Create chatbot_personas table (missing from main schema)
\i 002_create_chatbot_personas_table.sql

-- Migration 003: Create agent_session_assignments table (missing from main schema)
\i 003_create_agent_session_assignments_table.sql

-- Verify all tables were created successfully
SELECT 
    table_name,
    table_type
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'chatbot_personas',
        'agent_session_assignments'
    )
ORDER BY table_name;

-- Verify columns were added to existing tables
SELECT 
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_schema = 'public' 
    AND table_name = 'admins' 
    AND column_name = 'status';

-- Check what tables already exist in the main schema
SELECT 
    table_name,
    'EXISTS' as status
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'admins', 'human_agents', 'users', 'chat_sessions', 'chat_messages',
        'session_assignments', 'file_uploads', 'configuration_metadata',
        'widget_configuration', 'widget_suggested_messages', 'notification_settings',
        'security_settings', 'llm_providers', 'persona_configurations',
        'notifications', 'chat_feedback', 'token_usage_log', 'metrics',
        'email_oauth_credentials', 'user_unique_ids', 'scraped_websites',
        'api_usage', 'widget_scripts'
    )
ORDER BY table_name;

-- Success message
SELECT 'Missing migrations completed successfully!' as migration_status;
