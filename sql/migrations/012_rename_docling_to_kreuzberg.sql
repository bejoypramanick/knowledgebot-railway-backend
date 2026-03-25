-- Migration: Rename Docling to Kreuzberg (2026 Modernization)
-- Description: Renames all docling-branded columns and indexes in the file_uploads table to kreuzberg.

-- 1. Rename Columns in file_uploads
ALTER TABLE file_uploads RENAME COLUMN processed_by_docling TO processed_by_extractor;
ALTER TABLE file_uploads RENAME COLUMN docling_processing_time_ms TO extractor_processing_time_ms;
ALTER TABLE file_uploads RENAME COLUMN docling_images_extracted TO extractor_images_extracted;
ALTER TABLE file_uploads RENAME COLUMN docling_images_with_ocr TO extractor_images_with_ocr;

-- 2. Rename Columns in scraped_websites (if exists) - checking schema grep results
-- Based on grep, scraped_websites wasn't explicitly showing docling_ columns, 
-- but we should be safe and check if they were added in later iterations.
-- For now, focusing on file_uploads which is confirmed.

-- 3. Update Indexes
DROP INDEX IF EXISTS idx_file_uploads_docling_perf;
CREATE INDEX idx_file_uploads_extractor_perf ON file_uploads(extractor_processing_time_ms DESC)
  INCLUDE (extractor_images_extracted, extractor_images_with_ocr, processed_by_extractor)
  WHERE processed_by_extractor = true AND extractor_processing_time_ms > 0;

-- 4. Update any metadata references if necessary (handled by application logic)

COMMENT ON COLUMN file_uploads.processed_by_extractor IS 'Flag indicating if file was processed by the extraction service';
COMMENT ON COLUMN file_uploads.extractor_processing_time_ms IS 'Time taken by the extraction service to extract content in milliseconds';
