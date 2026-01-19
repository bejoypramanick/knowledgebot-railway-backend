-- Verify that the database has required indexes

-- Check admins table structure (should NOT have profile columns)
SELECT 'Admins table core columns:' as check_type;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'admins'
ORDER BY ordinal_position;

-- Check human_agents table structure (should NOT have profile columns)
SELECT 'Human Agents table core columns:' as check_type;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'human_agents'
ORDER BY ordinal_position;

-- Check if indexes were created
SELECT 'Indexes created:' as check_type;
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename IN ('admins', 'human_agents')
AND indexname LIKE '%email%status%'
ORDER BY tablename, indexname;

-- Test a simple query to see if it works
SELECT 'Testing profile query (should not error):' as check_type;
-- This simulates what the backend does
SELECT COUNT(*) as admin_count
FROM admins
WHERE status = 'confirmed'
LIMIT 1;

SELECT COUNT(*) as agent_count
FROM human_agents
WHERE status IN ('confirmed', 'pending')
LIMIT 1;