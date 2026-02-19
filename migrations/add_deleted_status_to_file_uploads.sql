-- Add 'deleted' status to file_uploads processing_status constraint
-- Purpose: Allow soft delete of file records by marking them as 'deleted'
-- Created: 2026-02-19

-- Drop the existing constraint
ALTER TABLE file_uploads
DROP CONSTRAINT valid_processing_status;

-- Add the new constraint with 'deleted' status
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

COMMENT ON CONSTRAINT valid_processing_status ON file_uploads IS 'Allowed processing statuses: pending, processing, completed, failed, cancelled, deleted';
