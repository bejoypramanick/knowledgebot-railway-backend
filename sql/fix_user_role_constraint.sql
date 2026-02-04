-- Fix file_uploads foreign key constraint issue
-- Make user_role_id nullable to allow file uploads without requiring user role mapping

-- Drop the foreign key constraint
ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS file_uploads_user_role_id_fkey;

-- Make user_role_id nullable
ALTER TABLE file_uploads ALTER COLUMN user_role_id DROP NOT NULL;

-- Set existing NULL values to a default or leave as NULL
UPDATE file_uploads SET user_role_id = NULL WHERE user_role_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM user_role_mapping WHERE user_role_id = file_uploads.user_role_id
);

-- Add comment
COMMENT ON COLUMN file_uploads.user_role_id IS 'Optional reference to user role mapping (nullable for system uploads)';
