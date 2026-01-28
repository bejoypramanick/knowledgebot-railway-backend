-- Master migration script to run all migrations in order
-- Execute this script to apply all missing tables and columns

-- Migration 001: Add missing columns
\i 001_add_missing_columns.sql

-- Migration 002: Create chatbot_personas table  
\i 002_create_chatbot_personas_table.sql

-- Migration 003: Create security_settings table
\i 003_create_security_settings_table.sql

-- Migration 004: Create llm_providers table
\i 004_create_llm_providers_table.sql

-- Migration 005: Create agent_session_assignments table
\i 005_create_agent_session_assignments_table.sql

-- Migration 006: Create suggested_messages table
\i 006_create_suggested_messages_table.sql

-- Migration 007: Create widget_configuration table
\i 007_create_widget_configuration_table.sql

-- Verify all tables were created successfully
SELECT 
    table_name,
    table_type
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'chatbot_personas',
        'security_settings', 
        'llm_providers',
        'agent_session_assignments',
        'suggested_messages',
        'widget_configuration'
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

-- Success message
SELECT 'All migrations completed successfully!' as migration_status;
