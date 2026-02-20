-- Migration: Add s3_key column to file_uploads table
-- Date: 2026-02-20
-- Description: Add s3_key column to store the S3 object key separately from the full URL

-- Add s3_key column to file_uploads table
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS s3_key TEXT NULL;

-- Add index for s3_key lookups
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_key ON public.file_uploads USING btree (s3_key);

-- Add comment
COMMENT ON COLUMN public.file_uploads.s3_key IS 'S3 object key (path within bucket) for the uploaded file';
