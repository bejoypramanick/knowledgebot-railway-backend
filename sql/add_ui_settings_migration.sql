-- Migration to add missing UI settings to widget_configuration and other tables
-- To support "Display Chatbot" toggle and other enhancements

-- 1. Add display_chatbot to widget_configuration
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS display_chatbot BOOLEAN DEFAULT TRUE;

-- 2. Ensure zoom and position columns exist (they seem to be used in code but might not be in the initial schema_3nf.sql provided earlier)
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS profile_zoom FLOAT DEFAULT 1.0;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS chat_icon_zoom FLOAT DEFAULT 1.0;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS profile_position JSONB DEFAULT '{"x": 0, "y": 0}'::jsonb;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS chat_icon_position JSONB DEFAULT '{"x": 0, "y": 0}'::jsonb;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS profile_picture_filename VARCHAR(255);
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS chat_icon_filename VARCHAR(255);

-- 3. Add hil_disabled_message to configuration_metadata (for Human in the Loop disabled state)
ALTER TABLE configuration_metadata ADD COLUMN IF NOT EXISTS hil_disabled_message TEXT DEFAULT 'Human assistance is currently offline. Please leave a message or try again later.';

-- 4. Add index for performance optimization if not exists
CREATE INDEX IF NOT EXISTS idx_chat_feedback_created_at ON chat_feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_role_created_at ON chat_messages(role, created_at DESC);
