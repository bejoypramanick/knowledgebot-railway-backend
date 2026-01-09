-- ============================================================================
-- TEMPORARY SCRIPT: Delete All Chats
-- ============================================================================
-- WARNING: This will permanently delete ALL chat data from the database!
-- 
-- This includes:
--   - All chat sessions
--   - All chat messages
--   - All human agent session assignments
--   - All chat feedback
--
-- This action CANNOT be undone!
--
-- Usage:
--   1. Connect to your PostgreSQL database
--   2. Review the counts below to see what will be deleted
--   3. Uncomment the DELETE statements at the bottom
--   4. Run this script
-- ============================================================================

-- First, let's see what we're about to delete
SELECT 'chat_sessions' as table_name, COUNT(*) as record_count FROM chat_sessions
UNION ALL
SELECT 'chat_messages' as table_name, COUNT(*) as record_count FROM chat_messages
UNION ALL
SELECT 'human_agent_sessions' as table_name, COUNT(*) as record_count 
FROM information_schema.tables 
WHERE table_name = 'human_agent_sessions'
  AND EXISTS (SELECT 1 FROM human_agent_sessions LIMIT 1)
UNION ALL
SELECT 'chat_feedback' as table_name, COUNT(*) as record_count 
FROM information_schema.tables 
WHERE table_name = 'chat_feedback'
  AND EXISTS (SELECT 1 FROM chat_feedback LIMIT 1);

-- ============================================================================
-- DELETE STATEMENTS
-- ============================================================================
-- Uncomment the statements below to actually delete the data
-- Make sure you've reviewed the counts above first!
-- ============================================================================

-- Delete chat feedback (if table exists)
-- DELETE FROM chat_feedback;

-- Delete human agent session assignments (if table exists)
-- DELETE FROM human_agent_sessions;

-- Delete all chat messages
-- DELETE FROM chat_messages;

-- Delete all chat sessions (this will also cascade delete messages if CASCADE is set)
-- DELETE FROM chat_sessions;

-- ============================================================================
-- VERIFICATION: Check that everything was deleted
-- ============================================================================
-- Run this after deletion to verify:

-- SELECT 'chat_sessions' as table_name, COUNT(*) as remaining_count FROM chat_sessions
-- UNION ALL
-- SELECT 'chat_messages' as table_name, COUNT(*) as remaining_count FROM chat_messages;

-- Both should return 0 if deletion was successful
