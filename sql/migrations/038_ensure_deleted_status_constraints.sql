-- Migration: 038_ensure_deleted_status_constraints
-- Description: Ensures that the 'deleted' status is valid for file_uploads and scraped_websites constraints.
-- This script should be run as the database owner.

-- 1. Fix file_uploads constraints
ALTER TABLE public.file_uploads DROP CONSTRAINT IF EXISTS valid_processing_status;
ALTER TABLE public.file_uploads DROP CONSTRAINT IF EXISTS file_uploads_processing_status_check;

ALTER TABLE public.file_uploads ADD CONSTRAINT valid_processing_status CHECK (
    processing_status::text = ANY (ARRAY[
        'pending'::text, 'processing'::text, 'completed'::text,
        'failed'::text, 'cancelled'::text, 'deleted'::text
    ])
);

COMMENT ON CONSTRAINT valid_processing_status ON public.file_uploads IS 'Valid processing statuses for file uploads including soft-delete marker';

-- 2. Fix scraped_websites constraints
ALTER TABLE public.scraped_websites DROP CONSTRAINT IF EXISTS valid_processing_status;
ALTER TABLE public.scraped_websites DROP CONSTRAINT IF EXISTS scraped_websites_processing_status_check;

ALTER TABLE public.scraped_websites ADD CONSTRAINT valid_processing_status CHECK (
    processing_status::text = ANY (ARRAY[
        'pending'::text, 'processing'::text, 'completed'::text,
        'failed'::text, 'cancelled'::text, 'deleted'::text
    ])
);

COMMENT ON CONSTRAINT valid_processing_status ON public.scraped_websites IS 'Valid processing statuses for website scrapes including soft-delete marker';
