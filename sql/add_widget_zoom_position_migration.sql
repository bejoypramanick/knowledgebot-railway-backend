-- Migration: Add zoom and position fields to widget_configuration table
-- This migration adds the necessary fields for image zoom and positioning functionality

-- Add zoom fields (decimal with 2 decimal places, default to 1.00 = 100%)
ALTER TABLE widget_configuration
ADD COLUMN profile_zoom DECIMAL(3,2) DEFAULT 1.00,
ADD COLUMN chat_icon_zoom DECIMAL(3,2) DEFAULT 1.00;

-- Add position fields (JSONB to store x,y coordinates)
ALTER TABLE widget_configuration
ADD COLUMN profile_position JSONB DEFAULT '{"x": 0, "y": 0}',
ADD COLUMN chat_icon_position JSONB DEFAULT '{"x": 0, "y": 0}';

-- Add comments for the new columns
COMMENT ON COLUMN widget_configuration.profile_zoom IS 'Zoom level for profile picture (1.00 = 100%)';
COMMENT ON COLUMN widget_configuration.chat_icon_zoom IS 'Zoom level for chat icon (1.00 = 100%)';
COMMENT ON COLUMN widget_configuration.profile_position IS 'Position offset for profile picture as JSON {"x": number, "y": number}';
COMMENT ON COLUMN widget_configuration.chat_icon_position IS 'Position offset for chat icon as JSON {"x": number, "y": number}';

-- Update existing records to have default values (if any exist)
UPDATE widget_configuration
SET
    profile_zoom = 1.00,
    chat_icon_zoom = 1.00,
    profile_position = '{"x": 0, "y": 0}',
    chat_icon_position = '{"x": 0, "y": 0}'
WHERE profile_zoom IS NULL OR chat_icon_zoom IS NULL;

-- Create indexes for the new columns (for potential future queries)
CREATE INDEX idx_widget_config_profile_zoom ON widget_configuration(profile_zoom);
CREATE INDEX idx_widget_config_chat_icon_zoom ON widget_configuration(chat_icon_zoom);
CREATE INDEX idx_widget_config_profile_position ON widget_configuration USING GIN(profile_position);
CREATE INDEX idx_widget_config_chat_icon_position ON widget_configuration USING GIN(chat_icon_position);