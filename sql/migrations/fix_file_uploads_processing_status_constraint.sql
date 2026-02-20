-- Migration: Fix file_uploads processing_status constraint to allow 'deleted'
-- Date: 2026-02-20
-- Description: The valid_processing_status constraint on file_uploads table doesn't allow 'deleted' status
--              This migration drops the old constraint and adds a new one that includes 'deleted'

-- Drop the old constraint that doesn't allow 'deleted'
ALTER TABLE file_uploads
DROP CONSTRAINT IF EXISTS valid_file_processing_status;

ALTER TABLE file_uploads
DROP CONSTRAINT IF EXISTS valid_processing_status;

-- Add a single, corrected constraint that allows all valid statuses including 'deleted'
ALTER TABLE file_uploads
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

COMMENT ON CONSTRAINT valid_processing_status ON file_uploads
IS 'Allowed processing statuses: pending, processing, completed, failed, cancelled, deleted';
