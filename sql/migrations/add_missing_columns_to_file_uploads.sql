-- Migration: Add missing columns to file_uploads table
-- Date: 2026-02-20
-- Description: Ensure file_uploads has all necessary columns matching scraped_websites pattern

-- Add s3_url column if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'file_uploads' AND column_name = 's3_url') THEN
        ALTER TABLE file_uploads ADD COLUMN s3_url text NULL;
        CREATE INDEX idx_file_uploads_s3_url ON file_uploads USING btree (s3_url);
        COMMENT ON COLUMN file_uploads.s3_url IS 'S3 storage URL for the uploaded file';
    END IF;
END $$;

-- Ensure processing_status column exists with correct constraint
DO $$ 
BEGIN
    -- Drop old constraints if they exist
    ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS valid_file_processing_status;
    ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS valid_processing_status;
    
    -- Add the correct constraint
    ALTER TABLE file_uploads ADD CONSTRAINT valid_processing_status CHECK (
        processing_status::text = ANY (ARRAY[
            'pending'::text,
            'processing'::text,
            'completed'::text,
            'failed'::text,
            'cancelled'::text,
            'deleted'::text
        ])
    );
END $$;

-- Ensure error_message column exists
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'file_uploads' AND column_name = 'error_message') THEN
        ALTER TABLE file_uploads ADD COLUMN error_message text NULL;
        COMMENT ON COLUMN file_uploads.error_message IS 'Error message if processing failed';
    END IF;
END $$;

-- Ensure celery_task_id column exists
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'file_uploads' AND column_name = 'celery_task_id') THEN
        ALTER TABLE file_uploads ADD COLUMN celery_task_id varchar(255) NULL;
        CREATE INDEX idx_file_uploads_celery_task_id ON file_uploads USING btree (celery_task_id);
        COMMENT ON COLUMN file_uploads.celery_task_id IS 'Celery task ID - used to revoke tasks from Redis queue when cancelled';
    END IF;
END $$;

-- Ensure task_revoked_at column exists
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'file_uploads' AND column_name = 'task_revoked_at') THEN
        ALTER TABLE file_uploads ADD COLUMN task_revoked_at timestamptz NULL;
        COMMENT ON COLUMN file_uploads.task_revoked_at IS 'Timestamp when task was revoked from queue';
    END IF;
END $$;

-- Update table comment
COMMENT ON TABLE file_uploads IS 'Uploaded files with Gemini FileSearch integration and Docling processing';

-- Update constraint comment
COMMENT ON CONSTRAINT valid_processing_status ON file_uploads 
IS 'Allowed processing statuses: pending, processing, completed, failed, cancelled, deleted';
