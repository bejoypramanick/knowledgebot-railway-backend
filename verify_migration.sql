-- Verify that the database migration added the required columns

-- Check admins table columns
SELECT 'Admins table columns:' as check_type;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'admins'
AND column_name IN ('display_name', 'photo_url', 'last_login', 'preferences', 'created_at', 'updated_at')
ORDER BY column_name;

-- Check human_agents table columns
SELECT 'Human Agents table columns:' as check_type;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'human_agents'
AND column_name IN ('display_name', 'photo_url', 'last_login', 'preferences', 'created_at', 'updated_at')
ORDER BY column_name;

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