-- Migration 014: Add usage tracking columns to chat and knowledge base tables
-- Run manually on Railway Postgres before deploying code changes.

-- Chat messages: per-message token and character usage
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS input_tokens INT DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS output_tokens INT DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS input_chars INT DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS output_chars INT DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS cached_tokens INT DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS cached_chars INT DEFAULT 0;

-- Chat sessions: aggregated totals per session
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_input_tokens INT DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_output_tokens INT DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_input_chars INT DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_output_chars INT DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_cached_tokens INT DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_cached_chars INT DEFAULT 0;

-- File uploads: Gemini FileSearch upload metrics
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS filestore_char_count INT DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS md_file_size INT DEFAULT 0;

-- Scraped websites: Gemini FileSearch upload metrics
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS filestore_char_count INT DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS md_file_size INT DEFAULT 0;
