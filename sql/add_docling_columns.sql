-- Migration: Add Docling processing columns to file_uploads table
-- This migration adds columns to track document processing with Docling
-- These columns are optional and used for analytics and debugging

-- Add docling-related columns to file_uploads table
ALTER TABLE file_uploads
ADD COLUMN IF NOT EXISTS processed_by_docling boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS docling_processing_time_ms int4,
ADD COLUMN IF NOT EXISTS original_file_extension varchar(50),
ADD COLUMN IF NOT EXISTS original_mime_type varchar(100),
ADD COLUMN IF NOT EXISTS docling_images_extracted int4 DEFAULT 0,
ADD COLUMN IF NOT EXISTS docling_images_with_ocr int4 DEFAULT 0;

-- Add index for tracking docling-processed files
CREATE INDEX IF NOT EXISTS idx_file_uploads_processed_by_docling
ON file_uploads(processed_by_docling)
WHERE processed_by_docling = true;

-- Add index for docling processing time analysis
CREATE INDEX IF NOT EXISTS idx_file_uploads_docling_processing_time
ON file_uploads(docling_processing_time_ms)
WHERE processed_by_docling = true;

-- Log migration completion
-- Note: PostgreSQL doesn't have native migration tracking in this simple schema
-- You can manually track this by recording in a migrations table if needed
