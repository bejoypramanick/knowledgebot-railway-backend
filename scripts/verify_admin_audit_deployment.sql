-- ============================================
-- Admin Audit System Verification Script
-- For DBeaver PostgreSQL
-- ============================================
-- Run this after deployment to verify all components are in place
--
-- Instructions:
-- 1. Open DBeaver
-- 2. Connect to Railway PostgreSQL
-- 3. Open SQL Editor
-- 4. Copy-paste this entire script
-- 5. Execute (Ctrl+Enter to run all, or run section by section)
-- ============================================

-- ============================================
-- SECTION 1: VERIFY TABLES EXIST
-- ============================================
SELECT 'TABLE VERIFICATION' AS section;

-- Check admin_sessions table
SELECT
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'admin_sessions'
    ) AS admin_sessions_exists;

-- Check admin_actions table
SELECT
    EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'admin_actions'
    ) AS admin_actions_exists;

-- ============================================
-- SECTION 2: VERIFY COLUMNS IN ADMIN_SESSIONS
-- ============================================
SELECT 'ADMIN_SESSIONS COLUMNS' AS section;

SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'admin_sessions'
ORDER BY ordinal_position;

-- ============================================
-- SECTION 3: VERIFY COLUMNS IN ADMIN_ACTIONS
-- ============================================
SELECT 'ADMIN_ACTIONS COLUMNS' AS section;

SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'admin_actions'
ORDER BY ordinal_position;

-- ============================================
-- SECTION 4: VERIFY INDEXES ON ADMIN_SESSIONS
-- ============================================
SELECT 'ADMIN_SESSIONS INDEXES' AS section;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'admin_sessions'
ORDER BY indexname;

-- ============================================
-- SECTION 5: VERIFY INDEXES ON ADMIN_ACTIONS
-- ============================================
SELECT 'ADMIN_ACTIONS INDEXES' AS section;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'admin_actions'
ORDER BY indexname;

-- ============================================
-- SECTION 6: VERIFY CONSTRAINTS ON ADMIN_SESSIONS
-- ============================================
SELECT 'ADMIN_SESSIONS CONSTRAINTS' AS section;

SELECT
    constraint_name,
    constraint_type,
    table_name
FROM information_schema.table_constraints
WHERE table_name = 'admin_sessions'
ORDER BY constraint_name;

-- ============================================
-- SECTION 7: VERIFY CONSTRAINTS ON ADMIN_ACTIONS
-- ============================================
SELECT 'ADMIN_ACTIONS CONSTRAINTS' AS section;

SELECT
    constraint_name,
    constraint_type,
    table_name
FROM information_schema.table_constraints
WHERE table_name = 'admin_actions'
ORDER BY constraint_name;

-- ============================================
-- SECTION 8: VERIFY VIEWS EXIST
-- ============================================
SELECT 'VIEWS VERIFICATION' AS section;

-- Check admin_sessions_analytics view
SELECT
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'admin_sessions_analytics'
    ) AS admin_sessions_analytics_exists;

-- Check admin_actions_analytics view
SELECT
    EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'admin_actions_analytics'
    ) AS admin_actions_analytics_exists;

-- ============================================
-- SECTION 9: VERIFY TRIGGERS
-- ============================================
SELECT 'TRIGGERS VERIFICATION' AS section;

SELECT
    trigger_name,
    event_object_table,
    event_manipulation,
    action_statement
FROM information_schema.triggers
WHERE event_object_table IN ('admin_sessions', 'admin_actions')
ORDER BY trigger_name;

-- ============================================
-- SECTION 10: TEST INSERT INTO ADMIN_SESSIONS
-- ============================================
SELECT 'TEST INSERT ADMIN_SESSIONS' AS section;

-- Insert test record
INSERT INTO admin_sessions (
    session_id,
    user_role_id,
    email,
    role_name,
    expires_at
) VALUES (
    '550e8400-e29b-41d4-a716-446655440000',
    1,
    'test-verification@example.com',
    'admin',
    NOW() + INTERVAL '8 hours'
) ON CONFLICT DO NOTHING;

-- Verify insert
SELECT
    id,
    session_id,
    email,
    role_name,
    is_active,
    action_count,
    created_at
FROM admin_sessions
WHERE email = 'test-verification@example.com'
LIMIT 1;

-- ============================================
-- SECTION 11: TEST INSERT INTO ADMIN_ACTIONS
-- ============================================
SELECT 'TEST INSERT ADMIN_ACTIONS' AS section;

-- Get the session ID for the foreign key
-- Insert test action record
INSERT INTO admin_actions (
    action_id,
    session_id,
    user_role_id,
    email,
    role_name,
    action_type,
    action_category,
    http_method,
    endpoint,
    duration_ms,
    success,
    response_status
) VALUES (
    '660e8400-e29b-41d4-a716-446655440001',
    (SELECT id FROM admin_sessions WHERE email = 'test-verification@example.com' LIMIT 1),
    1,
    'test-verification@example.com',
    'admin',
    'test.verify',
    'system',
    'POST',
    '/test',
    123,
    true,
    200
) ON CONFLICT DO NOTHING;

-- Verify insert
SELECT
    action_id,
    email,
    action_type,
    action_category,
    duration_ms,
    success,
    created_at
FROM admin_actions
WHERE email = 'test-verification@example.com'
LIMIT 1;

-- ============================================
-- SECTION 12: VERIFY TABLE STATISTICS
-- ============================================
SELECT 'TABLE STATISTICS' AS section;

SELECT
    'admin_sessions' AS table_name,
    COUNT(*) AS row_count
FROM admin_sessions
UNION ALL
SELECT
    'admin_actions' AS table_name,
    COUNT(*) AS row_count
FROM admin_actions;

-- ============================================
-- SECTION 13: CLEANUP TEST DATA
-- ============================================
SELECT 'CLEANUP TEST DATA' AS section;

-- Delete test records
DELETE FROM admin_actions
WHERE email = 'test-verification@example.com';

DELETE FROM admin_sessions
WHERE email = 'test-verification@example.com';

SELECT 'Test data cleanup complete' AS status;

-- ============================================
-- SECTION 14: FINAL VERIFICATION SUMMARY
-- ============================================
SELECT 'FINAL VERIFICATION SUMMARY' AS section;

SELECT
    CASE
        WHEN admin_sessions_exists AND admin_actions_exists THEN 'PASS'
        ELSE 'FAIL'
    END AS tables_created,

    CASE
        WHEN sessions_indexes > 0 AND actions_indexes > 0 THEN 'PASS'
        ELSE 'FAIL'
    END AS indexes_created,

    CASE
        WHEN sessions_constraints > 0 AND actions_constraints > 0 THEN 'PASS'
        ELSE 'FAIL'
    END AS constraints_created,

    CASE
        WHEN analytics_views > 0 THEN 'PASS'
        ELSE 'FAIL'
    END AS views_created
FROM (
    SELECT
        EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'admin_sessions'
        ) AS admin_sessions_exists,

        EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'admin_actions'
        ) AS admin_actions_exists,

        (SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'admin_sessions') AS sessions_indexes,
        (SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'admin_actions') AS actions_indexes,

        (SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_name = 'admin_sessions') AS sessions_constraints,
        (SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_name = 'admin_actions') AS actions_constraints,

        (SELECT COUNT(*) FROM information_schema.views WHERE table_name IN ('admin_sessions_analytics', 'admin_actions_analytics')) AS analytics_views
) AS verification;

-- ============================================
-- END OF VERIFICATION SCRIPT
-- ============================================
-- All sections completed successfully!
-- If you see PASS for all items above, deployment was successful.
-- ============================================
