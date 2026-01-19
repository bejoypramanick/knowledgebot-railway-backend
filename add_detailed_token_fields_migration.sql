-- Migration to add detailed token usage fields for better tracking
-- This adds fields for cache tokens (OpenAI) and detailed Gemini token breakdown

ALTER TABLE token_usage_log
ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS cache_write_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS input_audio_tokens INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS cache_audio_read_tokens INTEGER DEFAULT 0;

COMMENT ON COLUMN token_usage_log.cache_read_tokens IS 'Tokens read from cache (OpenAI prompt caching)';
COMMENT ON COLUMN token_usage_log.cache_write_tokens IS 'Tokens written to cache (OpenAI prompt caching)';
COMMENT ON COLUMN token_usage_log.input_audio_tokens IS 'Audio input tokens (multimodal models)';
COMMENT ON COLUMN token_usage_log.cache_audio_read_tokens IS 'Audio tokens read from cache';

-- Update existing records to have proper total_tokens calculation
UPDATE token_usage_log
SET total_tokens = COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)
WHERE total_tokens = 0 OR total_tokens IS NULL;