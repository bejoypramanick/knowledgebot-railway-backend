-- Migration: Add s3_url field to file_uploads table
-- Purpose: Store Railway S3 bucket URL for uploaded files
-- Date: 2026-02-20

-- Add s3_url column to file_uploads table
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS s3_url TEXT NULL;

-- Add index for s3_url lookups
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_url 
ON public.file_uploads USING btree (s3_url);

-- Add comment
COMMENT ON COLUMN public.file_uploads.s3_url IS 'Railway S3 bucket URL for the uploaded file';
