-- Verification script: Check which tables are actually used in the codebase
-- Run this to confirm before dropping any tables

-- Check current table structure
SELECT
    'Current tables in database:' as info;
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'public'
AND tablename NOT LIKE 'pg_%'
AND tablename NOT LIKE 'sql_%'
ORDER BY tablename;

-- Tables that SHOULD be kept (referenced in current codebase):
SELECT
    'Tables that should be KEPT (referenced in codebase):' as info;

-- These tables are referenced in the current codebase:
-- admins, human_agents, user_unique_ids, configuration_metadata,
-- notification_settings, security_settings, llm_providers,
-- persona_configurations, widget_configuration, widget_suggested_messages,
-- widget_scripts, chat_sessions, chat_messages, chat_feedback

-- Tables that can be DROPPED (not referenced in current codebase):
SELECT
    'Tables that can be DROPPED (not referenced in codebase):' as info;

-- After thorough analysis, these tables are ACTUALLY USED in backend services:
-- session_assignments (chat_log.py), file_uploads (knowledgebase_ingestion, chatbot_orchestration),
-- scraped_websites (website_scraping), api_usage (knowledgebase_ingestion),
-- metrics (chatbot_orchestration), notifications (notifications.py), email_oauth_credentials (referenced)

-- Only these can be safely dropped:
-- users, user_profiles

-- Check for any foreign key relationships before dropping
SELECT
    'Foreign key constraints (check before dropping tables):' as info;
SELECT
    tc.table_schema,
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
  AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
  AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
AND tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_name;

-- Check table sizes to see if they contain data
SELECT
    'Table sizes (check for data before dropping):' as info;
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    n_tup_ins - n_tup_del as estimated_rows
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- SUMMARY: After thorough backend code analysis, ALL tables in the current schema
-- are actually being used by the services. Only 'users' and 'user_profiles' tables
-- can be safely removed as they were replaced by the role-based table architecture.