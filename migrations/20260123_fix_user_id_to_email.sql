-- Migration: Fix user_id columns to use email strings instead of UUIDs
-- Since the system uses admins/human_agents tables, user identification should be by email

-- Change api_usage table user_id column to user_email
ALTER TABLE api_usage RENAME COLUMN user_id TO user_email;
ALTER TABLE api_usage ALTER COLUMN user_email TYPE VARCHAR(255);

-- Change file_uploads table user_id column to user_email
ALTER TABLE file_uploads RENAME COLUMN user_id TO user_email;
ALTER TABLE file_uploads ALTER COLUMN user_email TYPE VARCHAR(255);

-- Change metrics table user_id column to user_email (if it exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'metrics' AND column_name = 'user_id') THEN
        ALTER TABLE metrics RENAME COLUMN user_id TO user_email;
        ALTER TABLE metrics ALTER COLUMN user_email TYPE VARCHAR(255);
    END IF;
END $$;

-- Add indexes for the renamed columns
CREATE INDEX IF NOT EXISTS idx_api_usage_user_email ON api_usage(user_email);
CREATE INDEX IF NOT EXISTS idx_file_uploads_user_email ON file_uploads(user_email);
CREATE INDEX IF NOT EXISTS idx_metrics_user_email ON metrics(user_email);

-- Update comments
COMMENT ON COLUMN api_usage.user_email IS 'User email address (from Firebase auth)';
COMMENT ON COLUMN file_uploads.user_email IS 'User email address who uploaded the file';

-- Verify the changes
SELECT
    'api_usage table columns:' as table_info,
    array_agg(column_name::text || ' (' || data_type || ')') as columns
FROM information_schema.columns
WHERE table_name = 'api_usage' AND table_schema = 'public'
    AND column_name LIKE '%user%';

SELECT
    'file_uploads table columns:' as table_info,
    array_agg(column_name::text || ' (' || data_type || ')') as columns
FROM information_schema.columns
WHERE table_name = 'file_uploads' AND table_schema = 'public'
    AND column_name LIKE '%user%';