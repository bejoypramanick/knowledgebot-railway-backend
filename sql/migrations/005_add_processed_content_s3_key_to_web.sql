-- Migration: Add processed_content_s3_key to scraped_websites table
-- Stores S3 path of converted markdown after docling processing
-- Enables download endpoint for processed web content (same as files)
-- Run manually on Railway Postgres

ALTER TABLE scraped_websites
ADD COLUMN IF NOT EXISTS processed_content_s3_key text;
