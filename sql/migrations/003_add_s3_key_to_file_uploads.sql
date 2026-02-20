-- Migration: Add s3_key column and remove s3_url from file_uploads table
-- Date: 2026-02-20
-- Description: Replace s3_url with s3_key to store only the S3 object key

-- Add s3_key column to file_uploads table
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS s3_key TEXT NULL;

-- Add index for s3_key lookups
CREATE INDEX IF NOT EXISTS idx_file_uploads_s3_key ON public.file_uploads USING btree (s3_key);

-- Add comment
COMMENT ON COLUMN public.file_uploads.s3_key IS 'S3 object key (path within bucket) for the uploaded file';

-- Drop the redundant s3_url column (if it exists)
ALTER TABLE public.file_uploads 
DROP COLUMN IF EXISTS s3_url;

-- Drop the s3_url index (if it exists)
DROP INDEX IF EXISTS idx_file_uploads_s3_url;
