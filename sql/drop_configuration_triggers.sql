-- Drop existing triggers if they exist (run this first if you get trigger errors)
-- This is safe to run multiple times
-- 
-- IMPORTANT: We only drop the triggers, NOT the function, because other tables
-- (file_uploads, scraped_websites, chat_sessions, users) still use it.

DROP TRIGGER IF EXISTS update_chatbot_config_updated_at ON chatbot_configuration;
DROP TRIGGER IF EXISTS update_widget_config_updated_at ON widget_configuration;

-- Note: We do NOT drop the update_updated_at_column() function because it's used by other tables
-- The function is shared across multiple tables, so we only drop our specific triggers
-- updated_at for configuration tables is now handled in application code, not via triggers
-- This avoids trigger overhead and gives better control

