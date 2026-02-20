-- Migration: Add s3_url and celery_task_id fields to file_uploads table
-- Purpose: Store Railway S3 bucket URL and Celery task ID for uploaded files
-- Date: 2026-02-20

-- Add s3_url column to file_uploads table
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS s3_url TEXT NULL;

-- Add celery_task_id column to file_uploads table (for tracking async processing)
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255) NULL;

-- Add indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_url 
ON public.file_uploads USING btree (s3_url);

CREATE INDEX IF NOT EXISTS idx_file_uploads_celery_task_id 
ON public.file_uploads USING btree (celery_task_id);

-- Add comments
COMMENT ON COLUMN public.file_uploads.s3_url IS 'Railway S3 bucket URL for the uploaded file';
COMMENT ON COLUMN public.file_uploads.celery_task_id IS 'Celery task ID for async file processing';
