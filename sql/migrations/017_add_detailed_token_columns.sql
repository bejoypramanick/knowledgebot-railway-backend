-- Migration 017: Add detailed token tracking columns
-- token_count remains as-is (prompt_tokens for user, completion_tokens for bot)
-- New columns track per-message token count and explicit prompt/completion tokens
-- Run manually on Railway Postgres BEFORE deploying code

-- Per-message token count (just the message text, via count_tokens API)
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS message_token_count int4 DEFAULT 0;
-- Explicit prompt/completion token columns
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS prompt_token_count int4 DEFAULT 0;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS completion_token_count int4 DEFAULT 0;

-- Session aggregates for the new columns
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_message_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_prompt_token_count int4 DEFAULT 0;
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS total_completion_token_count int4 DEFAULT 0;
