-- Migration to fix file_uploads table schema mismatch
-- Add missing columns and modify existing ones to match the code expectations

-- Add user_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'file_uploads' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE file_uploads ADD COLUMN user_id varchar(255);
        CREATE INDEX idx_file_uploads_user_id ON file_uploads USING btree (user_id);
    END IF;
END $$;

-- Add processed_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'file_uploads' AND column_name = 'processed_at'
    ) THEN
        ALTER TABLE file_uploads ADD COLUMN processed_at timestamptz;
        CREATE INDEX idx_file_uploads_processed_at ON file_uploads USING btree (processed_at);
    END IF;
END $$;

-- Ensure size_bytes column exists (rename from file_size if needed)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'file_uploads' AND column_name = 'file_size'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'file_uploads' AND column_name = 'size_bytes'
    ) THEN
        ALTER TABLE file_uploads RENAME COLUMN file_size TO size_bytes;
    END IF;
END $$;

-- Add size_bytes column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'file_uploads' AND column_name = 'size_bytes'
    ) THEN
        ALTER TABLE file_uploads ADD COLUMN size_bytes int8;
    END IF;
END $$;

-- Copy data from user_role_id to user_id if user_id is empty and user_role_id exists
UPDATE file_uploads 
SET user_id = user_role_id::text 
WHERE user_id IS NULL AND user_role_id IS NOT NULL;

-- Add comments
COMMENT ON COLUMN file_uploads.user_id IS 'User ID from authentication (fallback for user_role_id)';
COMMENT ON COLUMN file_uploads.processed_at IS 'When the file was processed by Gemini';
COMMENT ON COLUMN file_uploads.size_bytes IS 'File size in bytes (renamed from file_size)';
