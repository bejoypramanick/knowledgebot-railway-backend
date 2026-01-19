-- Migration: Drop truly unused tables from the database
-- This removes tables that are NOT referenced in the current codebase
-- Run this after confirming the minimal schema works correctly

-- WARNING: This will permanently delete data from unused tables!
-- Make sure to backup any important data before running this.

-- After analyzing the backend code, these tables are ACTUALLY USED:
-- session_assignments, file_uploads, scraped_websites, api_usage,
-- metrics, notifications, email_oauth_credentials

-- Only drop these truly unused tables:
-- Drop the old user_profiles table (we moved this data to admins/human_agents tables)
DROP TABLE IF EXISTS user_profiles;

-- Drop the old users table (replaced by admins/human_agents role-based tables)
DROP TABLE IF EXISTS users;

-- Verify remaining tables (should match our minimal schema)
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'public'
AND tablename NOT LIKE 'pg_%'
AND tablename NOT LIKE 'sql_%'
ORDER BY tablename;

-- Expected remaining tables after cleanup:
-- admins, human_agents, user_unique_ids, configuration_metadata,
-- notification_settings, security_settings, llm_providers,
-- persona_configurations, widget_configuration, widget_suggested_messages,
-- widget_scripts, chat_sessions, chat_messages, chat_feedback