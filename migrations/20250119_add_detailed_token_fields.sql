-- Migration: Add detailed token usage fields
-- Date: 2025-01-19
-- Description: Adds cache and audio token fields to token_usage_log table for better token tracking
-- Version: 1.0

-- Add detailed token usage fields to support OpenAI cache tokens and audio tokens
ALTER TABLE token_usage_log
ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS cache_write_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS input_audio_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS cache_audio_read_tokens INTEGER DEFAULT 0;

-- Add comments for documentation
COMMENT ON COLUMN token_usage_log.cache_read_tokens IS 'Tokens read from cache (OpenAI prompt caching)';
COMMENT ON COLUMN token_usage_log.cache_write_tokens IS 'Tokens written to cache (OpenAI prompt caching)';
COMMENT ON COLUMN token_usage_log.input_audio_tokens IS 'Audio input tokens (multimodal models)';
COMMENT ON COLUMN token_usage_log.cache_audio_read_tokens IS 'Audio tokens read from cache';

-- Update existing records to have proper total_tokens calculation
UPDATE token_usage_log
SET total_tokens = COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)
WHERE total_tokens = 0 OR total_tokens IS NULL;

-- Log the migration completion
-- You can verify the migration ran successfully with:
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'token_usage_log' AND column_name IN ('cache_read_tokens', 'cache_write_tokens', 'input_audio_tokens', 'cache_audio_read_tokens');