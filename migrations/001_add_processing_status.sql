-- Migration: Add processing_status columns for async task tracking
-- File: migrations/001_add_processing_status.sql
-- Usage: psql -d your_database -f migrations/001_add_processing_status.sql

-- Add processing_status and error_message columns to file_uploads
ALTER TABLE file_uploads
ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN IF NOT EXISTS error_message TEXT,
ADD CONSTRAINT valid_file_processing_status CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'));

-- Create indexes on file_uploads for efficient polling
CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_status
ON file_uploads(processing_status);

CREATE INDEX IF NOT EXISTS idx_file_uploads_processing_pending
ON file_uploads(processing_status)
WHERE processing_status IN ('pending', 'processing');

-- Add processing_status and error_message columns to scraped_websites
ALTER TABLE scraped_websites
ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'completed',
ADD COLUMN IF NOT EXISTS error_message TEXT,
ADD CONSTRAINT valid_website_processing_status CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'));

-- Create indexes on scraped_websites for efficient polling
CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_status
ON scraped_websites(processing_status);

CREATE INDEX IF NOT EXISTS idx_scraped_websites_processing_pending
ON scraped_websites(processing_status)
WHERE processing_status IN ('pending', 'processing');

-- Migration complete
COMMIT;
