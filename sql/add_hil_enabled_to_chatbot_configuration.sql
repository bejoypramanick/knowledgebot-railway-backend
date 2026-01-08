-- Migration: Add hil_enabled column to chatbot_configuration table
-- Run this script manually on your PostgreSQL database
-- Date: 2025-01-XX

-- Add hil_enabled column to chatbot_configuration table
-- This column controls whether Human-in-the-Loop (human agent support) is enabled
-- Default value is TRUE (enabled by default)
ALTER TABLE chatbot_configuration 
ADD COLUMN IF NOT EXISTS hil_enabled BOOLEAN DEFAULT TRUE;

-- Update existing rows to have hil_enabled = TRUE if it's NULL
UPDATE chatbot_configuration 
SET hil_enabled = TRUE 
WHERE hil_enabled IS NULL;

-- Add comment to column for documentation
COMMENT ON COLUMN chatbot_configuration.hil_enabled IS 
'Controls whether Human-in-the-Loop (human agent support) is enabled. Default is TRUE.';

-- Verify the column was added
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'chatbot_configuration' 
AND column_name = 'hil_enabled';
