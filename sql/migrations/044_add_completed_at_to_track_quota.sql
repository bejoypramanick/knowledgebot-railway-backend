-- Migration: 044_add_completed_at_to_track_quota
-- Description: Add completed_at column to track when content first completed for quota purposes.
-- This allows quota to be "write-once" - deleting content does NOT reduce usage.

-- Add completed_at column to file_uploads
ALTER TABLE public.file_uploads 
ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

COMMENT ON COLUMN public.file_uploads.completed_at IS 'Timestamp when file processing first completed. Used for quota tracking - quota is write-once.';

-- Add completed_at column to scraped_websites  
ALTER TABLE public.scraped_websites
ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

COMMENT ON COLUMN public.scraped_websites.completed_at IS 'Timestamp when website scraping first completed. Used for quota tracking - quota is write-once.';

-- Backfill completed_at for existing completed records
UPDATE public.file_uploads 
SET completed_at = updated_at 
WHERE processing_status = 'completed' 
  AND completed_at IS NULL;

UPDATE public.scraped_websites
SET completed_at = updated_at
WHERE processing_status = 'completed'
  AND parent_id IS NULL
  AND completed_at IS NULL;
