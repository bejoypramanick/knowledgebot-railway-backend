-- Migration: Remove all database triggers
-- This migration drops all triggers and the trigger function
-- Application code will now manually handle updated_at timestamps

-- Drop all triggers
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
DROP TRIGGER IF EXISTS update_configuration_metadata_updated_at ON configuration_metadata;
DROP TRIGGER IF EXISTS update_notification_settings_updated_at ON notification_settings;
DROP TRIGGER IF EXISTS update_security_settings_updated_at ON security_settings;
DROP TRIGGER IF EXISTS update_llm_providers_updated_at ON llm_providers;
DROP TRIGGER IF EXISTS update_persona_configurations_updated_at ON persona_configurations;
DROP TRIGGER IF EXISTS update_widget_config_updated_at ON widget_configuration;
DROP TRIGGER IF EXISTS update_chat_sessions_updated_at ON chat_sessions;
DROP TRIGGER IF EXISTS update_file_uploads_updated_at ON file_uploads;
DROP TRIGGER IF EXISTS update_scraped_websites_updated_at ON scraped_websites;
DROP TRIGGER IF EXISTS update_user_unique_ids_updated_at ON user_unique_ids;
DROP TRIGGER IF EXISTS update_widget_suggested_messages_updated_at ON widget_suggested_messages;
DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;

-- Drop the trigger function
DROP FUNCTION IF EXISTS update_updated_at_column();

-- Migration complete
SELECT 'All database triggers removed successfully' as result;