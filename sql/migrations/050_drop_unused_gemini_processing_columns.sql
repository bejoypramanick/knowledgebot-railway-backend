-- Migration 050: Drop unused Gemini-era processing columns
-- These columns are no longer read by the application. Processing state is
-- driven by processing_status, and embedding usage is tracked separately.

ALTER TABLE IF EXISTS public.file_uploads
    DROP COLUMN IF EXISTS gemini_processed_at,
    DROP COLUMN IF EXISTS is_processing;

ALTER TABLE IF EXISTS public.scraped_websites
    DROP COLUMN IF EXISTS gemini_processed_at;
