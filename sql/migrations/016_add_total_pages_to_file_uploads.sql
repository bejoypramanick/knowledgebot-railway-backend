-- Migration 016: Add total_pages column to file_uploads
-- Run manually on Railway Postgres BEFORE deploying code

ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS total_pages int4 DEFAULT 0;
