-- Migration 014: Add usage tracking columns (character_count, word_count, token_count)
-- Run manually on Railway Postgres BEFORE deploying code

-- chat_messages: per-message metrics
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS character_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS word_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS token_count int4 DEFAULT 0;

-- chat_sessions: aggregated session metrics
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_character_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_word_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_token_count int4 DEFAULT 0;

-- file_uploads: filestore metrics (md content sent to Gemini FileSearch)
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS filestore_character_count int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS filestore_word_count int4 DEFAULT 0;
ALTER TABLE file_uploads ADD COLUMN IF NOT EXISTS filestore_token_count int4 DEFAULT 0;

-- scraped_websites: filestore metrics (md content sent to Gemini FileSearch)
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS filestore_character_count int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS filestore_word_count int4 DEFAULT 0;
ALTER TABLE scraped_websites ADD COLUMN IF NOT EXISTS filestore_token_count int4 DEFAULT 0;
