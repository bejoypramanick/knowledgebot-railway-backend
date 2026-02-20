-- Migration: Add char_count column and rename content_length to file_size

-- Step 1: Add char_count column to file_uploads
ALTER TABLE file_uploads
ADD COLUMN char_count INT DEFAULT 0;

COMMENT ON COLUMN file_uploads.char_count IS 'Number of characters in the file content (after markdown processing)';

-- Step 2: Add char_count column to scraped_websites
ALTER TABLE scraped_websites
ADD COLUMN char_count INT DEFAULT 0;

COMMENT ON COLUMN scraped_websites.char_count IS 'Number of characters in the scraped website content (after markdown processing)';

-- Step 3: Rename content_length to file_size in scraped_websites
ALTER TABLE scraped_websites
RENAME COLUMN content_length TO file_size;

COMMENT ON COLUMN scraped_websites.file_size IS 'Size of the markdown file in bytes (for display in UI)';

-- Step 4: Create indexes for the new columns
CREATE INDEX IF NOT EXISTS idx_file_uploads_char_count ON file_uploads(char_count);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_char_count ON scraped_websites(char_count);
CREATE INDEX IF NOT EXISTS idx_scraped_websites_file_size ON scraped_websites(file_size);

-- Migration timestamp
-- 2026-02-19: Add character count tracking and standardize file_size column naming
