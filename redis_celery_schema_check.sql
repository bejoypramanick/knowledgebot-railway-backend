-- Redis Celery Setup - Database Schema Validation Query
-- Checks all required table columns exist for async file/website processing

-- ============================================================================
-- 1. FILE UPLOADS TABLE - REQUIRED COLUMNS FOR CELERY
-- ============================================================================
SELECT
    'file_uploads' AS table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name = 'file_uploads'
    AND column_name IN (
        'id',                          -- Primary key
        'processing_status',           -- Celery: pending/processing/completed/failed
        'error_message',               -- Celery: error tracking
        'metadata',                    -- FileSearch metadata storage (JSONB)
        'created_at',                  -- Timestamp
        'updated_at',                  -- Timestamp
        'gemini_file_name',            -- File reference
        'gemini_state',                -- Gemini processing status
        'original_filename'            -- For logging
    )
ORDER BY ordinal_position;

-- ============================================================================
-- 2. SCRAPED WEBSITES TABLE - REQUIRED COLUMNS FOR CELERY
-- ============================================================================
SELECT
    'scraped_websites' AS table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name = 'scraped_websites'
    AND column_name IN (
        'id',                          -- Primary key
        'processing_status',           -- Celery: pending/processing/completed/failed
        'error_message',               -- Celery: error tracking
        'metadata',                    -- Metadata storage (JSONB)
        'created_at',                  -- Timestamp
        'updated_at',                  -- Timestamp
        'gemini_file_name',            -- File reference
        'gemini_state',                -- Gemini processing status
        'original_url'                 -- URL reference
    )
ORDER BY ordinal_position;

-- ============================================================================
-- 3. VERIFICATION SUMMARY - MISSING COLUMNS
-- ============================================================================
-- FILE UPLOADS: Check which required columns are missing
WITH required_columns AS (
    SELECT 'id'::text AS col_name
    UNION ALL SELECT 'processing_status'
    UNION ALL SELECT 'error_message'
    UNION ALL SELECT 'metadata'
    UNION ALL SELECT 'created_at'
    UNION ALL SELECT 'updated_at'
)
SELECT
    'file_uploads - MISSING' AS status,
    rc.col_name AS missing_column
FROM required_columns rc
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns ic
    WHERE ic.table_schema = 'public'
        AND ic.table_name = 'file_uploads'
        AND ic.column_name = rc.col_name
);

-- SCRAPED WEBSITES: Check which required columns are missing
WITH required_columns AS (
    SELECT 'id'::text AS col_name
    UNION ALL SELECT 'processing_status'
    UNION ALL SELECT 'error_message'
    UNION ALL SELECT 'metadata'
    UNION ALL SELECT 'created_at'
    UNION ALL SELECT 'updated_at'
)
SELECT
    'scraped_websites - MISSING' AS status,
    rc.col_name AS missing_column
FROM required_columns rc
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns ic
    WHERE ic.table_schema = 'public'
        AND ic.table_name = 'scraped_websites'
        AND ic.column_name = rc.col_name
);

-- ============================================================================
-- 4. PROCESSING STATUS ENUM CONSTRAINT CHECK
-- ============================================================================
SELECT
    'file_uploads' AS table_name,
    constraint_name,
    'Valid values: pending, processing, completed, failed' AS expected_values
FROM information_schema.table_constraints
WHERE table_schema = 'public'
    AND table_name = 'file_uploads'
    AND constraint_type = 'CHECK'
    AND constraint_name LIKE '%processing_status%'

UNION ALL

SELECT
    'scraped_websites' AS table_name,
    constraint_name,
    'Valid values: pending, processing, completed, failed' AS expected_values
FROM information_schema.table_constraints
WHERE table_schema = 'public'
    AND table_name = 'scraped_websites'
    AND constraint_type = 'CHECK'
    AND constraint_name LIKE '%processing_status%';

-- ============================================================================
-- 5. FINAL SUMMARY - ALL CHECKS PASSED?
-- ============================================================================
SELECT
    COUNT(DISTINCT table_name) AS total_required_tables,
    COUNT(CASE WHEN table_name = 'file_uploads' THEN 1 END) AS file_uploads_exists,
    COUNT(CASE WHEN table_name = 'scraped_websites' THEN 1 END) AS scraped_websites_exists,
    CASE
        WHEN COUNT(DISTINCT table_name) = 2 THEN '✅ ALL TABLES EXIST'
        ELSE '❌ MISSING TABLES'
    END AS schema_status
FROM information_schema.tables
WHERE table_schema = 'public'
    AND table_name IN ('file_uploads', 'scraped_websites');

-- ============================================================================
-- 6. RECORD COUNT - FOR DEBUGGING
-- ============================================================================
SELECT 'file_uploads' AS table_name, COUNT(*) AS total_records FROM file_uploads
UNION ALL
SELECT 'scraped_websites', COUNT(*) FROM scraped_websites;

-- ============================================================================
-- 7. PROCESSING STATUS BREAKDOWN - CURRENT STATE
-- ============================================================================
SELECT
    'file_uploads' AS table_name,
    processing_status,
    COUNT(*) AS count
FROM file_uploads
GROUP BY processing_status
ORDER BY 2

UNION ALL

SELECT
    'scraped_websites' AS table_name,
    processing_status,
    COUNT(*) AS count
FROM scraped_websites
GROUP BY processing_status
ORDER BY 2;
