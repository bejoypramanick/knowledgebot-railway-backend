-- Fix scraped_websites processing_status constraints to allow 'deleted' status
-- Purpose: Allow soft delete of scraped website records
-- Created: 2026-02-19

-- Drop the old constraints that don't allow 'deleted'
ALTER TABLE scraped_websites
DROP CONSTRAINT IF EXISTS valid_processing_status;

ALTER TABLE scraped_websites
DROP CONSTRAINT IF EXISTS valid_website_processing_status;

-- Add a single, corrected constraint that allows all valid statuses including 'deleted'
ALTER TABLE scraped_websites
ADD CONSTRAINT valid_processing_status CHECK (
    processing_status::text = ANY (ARRAY[
        'pending'::text,
        'processing'::text,
        'completed'::text,
        'failed'::text,
        'cancelled'::text,
        'deleted'::text
    ])
);

COMMENT ON CONSTRAINT valid_processing_status ON scraped_websites
IS 'Allowed processing statuses: pending, processing, completed, failed, cancelled, deleted';
