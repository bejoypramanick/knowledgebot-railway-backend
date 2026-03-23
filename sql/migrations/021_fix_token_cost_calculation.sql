-- Migration 021: Fix token_usage_log pricing for Gemini 2.5 Flash Lite
-- Run on Railway Postgres BEFORE/AFTER deploying the DAO updates.

-- 1. Ensure manual cost_cents column exists (for Python-side precise tracking)
ALTER TABLE token_usage_log ADD COLUMN IF NOT EXISTS cost_cents int DEFAULT 0;

-- 2. Update the AUTOMATICally generated storage column to match 2.5 Flash Lite rates.
-- Old formula (0.003/0.006) was wrong. 
-- New Rates per 1M tokens: Input $0.10 (10c/1M), Output $0.40 (40c/1M)
-- Formula per token (cents): Input 0.00001, Output 0.00004
ALTER TABLE token_usage_log DROP COLUMN IF EXISTS calculated_cost_cents;
ALTER TABLE token_usage_log ADD COLUMN calculated_cost_cents int 
    GENERATED ALWAYS AS (ROUND((prompt_tokens * 0.00001 + completion_tokens * 0.00004)::numeric)::int) STORED;

-- 3. Performance indexing for Usage Report
-- Speeds up the aggregation queries used in /usage report by creating covering indexes
CREATE INDEX IF NOT EXISTS idx_token_usage_log_reporting 
    ON token_usage_log(created_at DESC, prompt_tokens, completion_tokens) 
    INCLUDE (cost_cents, api_call_type);

CREATE INDEX IF NOT EXISTS idx_tables_metadata_reporting
    ON tables_metadata(created_at DESC, table_input_token_count, table_output_token_count);
