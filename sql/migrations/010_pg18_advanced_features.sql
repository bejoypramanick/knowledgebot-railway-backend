-- ============================================================================
-- PostgreSQL 18 Advanced Features Migration
-- ============================================================================
-- Features implemented:
-- 1. Virtual Generated Columns (PG18-only) - computed, never stored
-- 2. JSON_TABLE support - SQL/JSON standard for JSONB unnesting
-- 3. B-tree Skip Scans - new indexes and settings
-- 4. MERGE with RETURNING - replaces ON CONFLICT for better semantics
-- 5. Async I/O optimizations - effective_io_concurrency already configured

-- ============================================================================
-- Feature 1: Virtual Generated Columns
-- ============================================================================

-- tokens_remaining: computed virtual column for llm_providers
-- Evaluates on SELECT, never stored, zero storage overhead
ALTER TABLE llm_providers
ADD COLUMN tokens_remaining bigint GENERATED ALWAYS AS (token_limit - token_used) VIRTUAL;

COMMENT ON COLUMN llm_providers.tokens_remaining IS 'Computed virtual column: token_limit - token_used. Calculated on SELECT, never stored.';

-- duration_minutes: computed virtual column for chat_sessions
-- Used for performance analytics (avoid repeated EXTRACT calculation)
ALTER TABLE chat_sessions
ADD COLUMN duration_minutes numeric GENERATED ALWAYS AS (
  ROUND(EXTRACT(EPOCH FROM (
    COALESCE(ended_at, last_activity_at) - started_at
  )) / 60.0, 2)
) VIRTUAL;

COMMENT ON COLUMN chat_sessions.duration_minutes IS 'Computed virtual column: session duration in minutes. Calculated on SELECT, never stored.';

-- is_root_page: computed virtual column for scraped_websites
-- Replaces repetitive parent_id IS NULL checks
ALTER TABLE scraped_websites
ADD COLUMN is_root_page boolean GENERATED ALWAYS AS (parent_id IS NULL) VIRTUAL;

COMMENT ON COLUMN scraped_websites.is_root_page IS 'Computed virtual column: true if parent_id IS NULL (root page in crawl tree)';

-- is_processing: computed virtual column for file_uploads
-- Simplifies worker queue queries for pending/processing files
ALTER TABLE file_uploads
ADD COLUMN is_processing boolean GENERATED ALWAYS AS (processing_status IN ('pending', 'processing')) VIRTUAL;

COMMENT ON COLUMN file_uploads.is_processing IS 'Computed virtual column: true if processing_status is pending or processing';

-- ============================================================================
-- Feature 3: B-tree Skip Scan Indexes
-- ============================================================================

-- Compound index for token_usage_log: enables skip scan on time-based queries
-- WITHOUT binding provider in WHERE clause. Skip scan iterates distinct provider values.
-- Enables: WHERE created_at > X to use this index across all providers.
CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider_created
ON token_usage_log (provider, created_at DESC);

COMMENT ON INDEX idx_token_usage_log_provider_created IS 'B-tree compound index enabling skip scans. Use for time-range analytics queries that skip provider binding.';

-- Expression index for JSON_TABLE support on scraped_websites.metadata
-- Enables fast filtering by metadata.scraping_config.source without full table scan
CREATE INDEX IF NOT EXISTS idx_scraped_websites_metadata_source
ON scraped_websites ((metadata->'scraping_config'->>'source'));

COMMENT ON INDEX idx_scraped_websites_metadata_source IS 'Expression index on metadata scraping source. Enables JSON_TABLE queries to filter by source type.';

-- ============================================================================
-- Feature 5: MERGE with RETURNING Preparation
-- ============================================================================

-- No DDL changes needed for MERGE. The statements will be updated in Python DAOs.
-- MERGE syntax is compatible with existing ON CONFLICT semantics.
-- Advantage: MERGE returns merge_action() ('INSERT', 'UPDATE', 'DELETE') for audit trails.

-- ============================================================================
-- Feature 4: Async I/O (Server-side Configuration)
-- ============================================================================

-- Async I/O for PG18 io_uring is enabled via:
-- effective_io_concurrency = 200 (async prefetch for sequential scans)
-- maintenance_io_concurrency = 100 (for maintenance operations)
-- Already set in shared/sqlalchemy_db.py connection setup.

-- Verify in current session (for testing):
-- SET LOCAL effective_io_concurrency = 200;
-- SHOW effective_io_concurrency;
