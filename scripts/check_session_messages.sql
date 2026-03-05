-- Check if messages exist for recent sessions
-- Run this query to verify messages are being stored

-- Get recent sessions with message counts
SELECT 
    cs.id as session_db_id,
    cs.session_id,
    cs.archive_status,
    cs.created_at,
    cs.last_activity_at,
    COUNT(cm.id) as message_count
FROM chat_sessions cs
LEFT JOIN chat_messages cm ON cs.id = cm.session_id
WHERE cs.created_at > NOW() - INTERVAL '1 day'
GROUP BY cs.id, cs.session_id, cs.archive_status, cs.created_at, cs.last_activity_at
ORDER BY cs.created_at DESC
LIMIT 20;

-- Get actual messages for a specific session (replace 362 with your session_db_id)
SELECT 
    id,
    session_id,
    role,
    LEFT(content, 100) as content_preview,
    created_at
FROM chat_messages
WHERE session_id IN (
    SELECT id FROM chat_sessions WHERE id IN (362, 361, 360, 359, 358, 357, 356, 355, 354, 353)
)
ORDER BY session_id DESC, created_at ASC;
