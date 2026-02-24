-- Migration: Add processed_content_s3_key column to file_uploads
-- Stores the S3 path of the converted markdown file after docling processing
-- Run manually on Railway Postgres

ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS processed_content_s3_key text;
