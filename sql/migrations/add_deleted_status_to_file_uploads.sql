-- Add 'deleted' status to file_uploads processing_status constraint
-- This allows soft-delete operations on files, matching the pattern used for scraped_websites
-- Handles both possible constraint names (manually created vs auto-generated)

ALTER TABLE file_uploads
DROP CONSTRAINT IF EXISTS valid_processing_status;

ALTER TABLE file_uploads
DROP CONSTRAINT IF EXISTS file_uploads_processing_status_check;

ALTER TABLE file_uploads
ADD CONSTRAINT valid_processing_status CHECK (
    processing_status::text = ANY (
        ARRAY[
            'pending'::text,
            'processing'::text,
            'completed'::text,
            'failed'::text,
            'cancelled'::text,
            'deleted'::text
        ]
    )
);

COMMENT ON CONSTRAINT valid_processing_status ON file_uploads IS 'Valid processing statuses for file uploads including soft-delete marker';
