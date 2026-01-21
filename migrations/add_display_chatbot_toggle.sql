-- Migration to add display_chatbot toggle to widget_configuration table
-- This allows administrators to control chat bubble visibility

ALTER TABLE widget_configuration
ADD COLUMN display_chatbot BOOLEAN DEFAULT true;

-- Add comment for the new column
COMMENT ON COLUMN widget_configuration.display_chatbot IS 'Controls whether the chat bubble is displayed on websites. When false, the chat widget is hidden.';

-- Update existing records to have display_chatbot = true (current behavior)
UPDATE widget_configuration
SET display_chatbot = true
WHERE display_chatbot IS NULL;