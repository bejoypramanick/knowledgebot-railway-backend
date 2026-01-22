-- Add hil_disabled_message column to configuration_metadata table
ALTER TABLE configuration_metadata
ADD COLUMN IF NOT EXISTS hil_disabled_message TEXT;

-- Add a comment for the new column
COMMENT ON COLUMN configuration_metadata.hil_disabled_message IS 'Message shown when Human-in-the-Loop is disabled';